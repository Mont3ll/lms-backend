import csv
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from io import StringIO
from typing import Any, Dict, List, Tuple, Optional
import uuid
from django.db import models
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Max, Min, Sum, Q, F, Case, When, IntegerField
from django.utils import timezone
from django.contrib.auth import get_user_model
import random

# Import models from other apps
from apps.core.models import Tenant
from apps.courses.models import Course
from apps.enrollments.models import Enrollment
from apps.users.models import User
from apps.assessments.models import AssessmentAttempt

# Import analytics models
from .models import (
    Event, Report, Dashboard, StudentEngagementMetric, CourseAnalytics,
    InstructorAnalytics, PredictiveAnalytics, AIInsights, RealTimeMetrics,
    LearningEfficiency, SocialLearningMetrics, StudySession, PeerReview,
    CollaborativeProject, StudyGroup, DiscussionInteraction, RevenueAnalytics
)

logger = logging.getLogger(__name__)

User = get_user_model()


class AnalyticsService:
    """Service for logging events and processing analytics data."""

    @staticmethod
    def track_event(
        user: User | None,
        event_type: str,
        context_data: Dict[str, Any] | None = None,
        tenant: Tenant | None = None,
        request=None,
    ):
        """Logs an event to the database."""
        if event_type not in [code for code, name in Event.EVENT_TYPES]:
            logger.warning(f"Attempted to track invalid event type: {event_type}")
            return

        # Ensure context_data doesn't contain non-serializable objects if not handled
        safe_context_data = context_data or {}
        try:
            # Minimal check, real validation might be needed
            json.dumps(safe_context_data)
        except TypeError:
            logger.error(
                f"Non-serializable data passed to track_event context_data for event {event_type}"
            )
            # Decide how to handle: strip invalid data, log error and skip, etc.
            safe_context_data = {"error": "Invalid context data provided"}

        event_data = {
            "user": user,
            "event_type": event_type,
            "context_data": safe_context_data,
            "tenant": tenant,
        }

        # Extract additional info from request if available
        if request:
            # Get IP Address safely
            x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
            if x_forwarded_for:
                event_data["ip_address"] = x_forwarded_for.split(",")[
                    0
                ].strip()  # Added strip
            else:
                event_data["ip_address"] = request.META.get("REMOTE_ADDR")

            # Get Session ID
            if (
                hasattr(request, "session")
                and request.session
                and request.session.session_key
            ):
                event_data["session_id"] = request.session.session_key

            # Enhanced user agent parsing
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            event_data['user_agent'] = user_agent
            
            # Basic device type detection
            if any(mobile in user_agent.lower() for mobile in ['mobile', 'android', 'iphone']):
                event_data['device_type'] = 'mobile'
            elif 'tablet' in user_agent.lower() or 'ipad' in user_agent.lower():
                event_data['device_type'] = 'tablet'
            else:
                event_data['device_type'] = 'desktop'
            
            # Basic browser detection
            if 'chrome' in user_agent.lower():
                event_data['browser'] = 'Chrome'
            elif 'firefox' in user_agent.lower():
                event_data['browser'] = 'Firefox'
            elif 'safari' in user_agent.lower():
                event_data['browser'] = 'Safari'
            elif 'edge' in user_agent.lower():
                event_data['browser'] = 'Edge'
            else:
                event_data['browser'] = 'Other'

        try:
            Event.objects.create(**event_data)
            logger.debug(f"Tracked event: {event_type} for user {user.id if user else 'None'}")
        except Exception as e:
            logger.error(f"Failed to track event {event_type}: {e}", exc_info=True)

    @staticmethod
    def process_student_engagement_metrics(tenant: Tenant, date: datetime.date = None):
        """Process and store student engagement metrics for a specific date."""
        if date is None:
            date = timezone.now().date() - timedelta(days=1)  # Previous day
        
        # Get all active enrollments for the tenant
        enrollments = Enrollment.objects.filter(
            course__tenant=tenant,
            status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED]
        ).select_related('user', 'course')
        
        for enrollment in enrollments:
            user = enrollment.user
            course = enrollment.course
            
            # Calculate engagement metrics from events
            events = Event.objects.filter(
                tenant=tenant,
                user=user,
                created_at__date=date,
                context_data__course_id=str(course.id)
            )
            
            daily_active_time = AnalyticsService._calculate_active_time(events)
            
            # Count various activities
            content_views = events.filter(event_type='CONTENT_VIEW').count()
            video_watches = events.filter(event_type='VIDEO_WATCH').count()
            quiz_attempts = events.filter(event_type='QUIZ_ATTEMPT').count()
            discussion_posts = events.filter(event_type='DISCUSSION_POST').count()
            assignments_submitted = events.filter(event_type='ASSIGNMENT_SUBMIT').count()
            
            # Calculate session metrics
            sessions = events.filter(event_type='SESSION_START')
            session_count = sessions.count()
            avg_session_duration = AnalyticsService._calculate_avg_session_duration(user, date)
            
            # Calculate risk score
            risk_score = AnalyticsService._calculate_risk_score(user, course, date)
            
            # Get or create engagement metric
            engagement_metric, created = StudentEngagementMetric.objects.get_or_create(
                tenant=tenant,
                user=user,
                course_id=course.id,
                date=date,
                defaults={
                    'daily_active_time': daily_active_time,
                    'content_views': content_views,
                    'video_watches': video_watches,
                    'quiz_attempts': quiz_attempts,
                    'discussion_posts': discussion_posts,
                    'assignments_submitted': assignments_submitted,
                    'session_count': session_count,
                    'avg_session_duration': avg_session_duration,
                    'risk_score': risk_score,
                    'last_activity_date': timezone.now(),
                }
            )
            
            if not created:
                # Update existing metric
                engagement_metric.daily_active_time = daily_active_time
                engagement_metric.content_views = content_views
                engagement_metric.video_watches = video_watches
                engagement_metric.quiz_attempts = quiz_attempts
                engagement_metric.discussion_posts = discussion_posts
                engagement_metric.assignments_submitted = assignments_submitted
                engagement_metric.session_count = session_count
                engagement_metric.avg_session_duration = avg_session_duration
                engagement_metric.risk_score = risk_score
                engagement_metric.last_activity_date = timezone.now()
                engagement_metric.save()

    @staticmethod
    def _calculate_active_time(events):
        """Calculate active time in minutes from events."""
        if not events.exists():
            return 0
        
        # Group events by session and calculate time spent
        sessions = {}
        for event in events:
            session_id = event.session_id or 'default'
            if session_id not in sessions:
                sessions[session_id] = []
            sessions[session_id].append(event.created_at)
        
        total_time = 0
        for session_events in sessions.values():
            if len(session_events) > 1:
                session_events.sort()
                # Calculate time difference between first and last event
                time_diff = (session_events[-1] - session_events[0]).total_seconds() / 60
                # Cap session time at 3 hours to avoid outliers
                total_time += min(time_diff, 180)
        
        return int(total_time)

    @staticmethod
    def _calculate_avg_session_duration(user: User, date: datetime.date):
        """Calculate average session duration for a user on a specific date."""
        from .models import StudySession
        
        # Try to get actual session data first
        sessions = StudySession.objects.filter(
            user=user,
            started_at__date=date,
            duration__isnull=False
        )
        
        if sessions.exists():
            # Calculate average from actual session durations
            total_duration = sum(
                (s.duration.total_seconds() / 60 for s in sessions),
                0
            )
            return int(total_duration / sessions.count())
        
        # Fallback: estimate from events by grouping SESSION_START/SESSION_END pairs
        events = Event.objects.filter(user=user, created_at__date=date).order_by('created_at')
        if not events.exists():
            return 0
        
        # Group events by session_id and calculate duration
        session_durations = []
        sessions_dict = {}
        
        for event in events:
            session_id = event.session_id or 'default'
            if session_id not in sessions_dict:
                sessions_dict[session_id] = {'start': None, 'end': None, 'events': []}
            
            sessions_dict[session_id]['events'].append(event.created_at)
            
            if event.event_type == 'SESSION_START':
                sessions_dict[session_id]['start'] = event.created_at
            elif event.event_type == 'SESSION_END':
                sessions_dict[session_id]['end'] = event.created_at
        
        for session_data in sessions_dict.values():
            if session_data['start'] and session_data['end']:
                # Use explicit session start/end
                duration = (session_data['end'] - session_data['start']).total_seconds() / 60
            elif len(session_data['events']) > 1:
                # Estimate from first to last event
                events_list = sorted(session_data['events'])
                duration = (events_list[-1] - events_list[0]).total_seconds() / 60
            else:
                # Single event, assume minimum session of 5 minutes
                duration = 5
            
            # Cap individual session at 3 hours to avoid outliers
            session_durations.append(min(duration, 180))
        
        if session_durations:
            return int(sum(session_durations) / len(session_durations))
        
        return 0

    @staticmethod
    def _calculate_risk_score(user: User, course: Course, date: datetime.date):
        """Calculate risk score for a student."""
        # This is a simplified risk calculation
        # In a real implementation, you'd use ML models
        
        # Get recent activity
        recent_events = Event.objects.filter(
            user=user,
            context_data__course_id=str(course.id),
            created_at__gte=date - timedelta(days=7)
        ).count()
        
        # Calculate risk factors
        risk_factors = []
        risk_score = 0
        
        if recent_events < 5:
            risk_factors.append("low_activity")
            risk_score += 30
        
        # Check quiz performance
        recent_quiz_attempts = Event.objects.filter(
            user=user,
            event_type='QUIZ_ATTEMPT',
            created_at__gte=date - timedelta(days=14)
        ).count()
        
        if recent_quiz_attempts == 0:
            risk_factors.append("no_quiz_attempts")
            risk_score += 25
        
        # Check login frequency
        recent_logins = Event.objects.filter(
            user=user,
            event_type='USER_LOGIN',
            created_at__gte=date - timedelta(days=7)
        ).count()
        
        if recent_logins < 3:
            risk_factors.append("infrequent_login")
            risk_score += 20
        
        return min(risk_score, 100)

    @staticmethod
    def process_course_analytics(tenant: Tenant, date: datetime.date = None):
        """Process and store course analytics for a specific date."""
        if date is None:
            date = timezone.now().date() - timedelta(days=1)
        
        courses = Course.objects.filter(tenant=tenant, status='published')
        
        for course in courses:
            # Get enrollment metrics
            total_enrollments = Enrollment.objects.filter(course=course).count()
            active_enrollments = Enrollment.objects.filter(
                course=course, 
                status=Enrollment.Status.ACTIVE
            ).count()
            completed_enrollments = Enrollment.objects.filter(
                course=course, 
                status=Enrollment.Status.COMPLETED
            ).count()
            dropped_enrollments = Enrollment.objects.filter(
                course=course, 
                status=Enrollment.Status.DROPPED
            ).count()
            
            # Calculate completion rate
            avg_completion_rate = (
                (completed_enrollments / total_enrollments * 100) 
                if total_enrollments > 0 else 0
            )
            
            # Get engagement metrics
            engagement_metrics = StudentEngagementMetric.objects.filter(
                course_id=course.id,
                date=date
            )
            
            avg_engagement_score = engagement_metrics.aggregate(
                avg_score=Avg('risk_score')
            )['avg_score'] or 0
            
            # Calculate revenue (simplified)
            total_revenue = total_enrollments * float(course.price or 0)
            avg_revenue_per_student = (
                total_revenue / total_enrollments if total_enrollments > 0 else 0
            )
            
            # Get or create course analytics
            course_analytics, created = CourseAnalytics.objects.get_or_create(
                tenant=tenant,
                course_id=course.id,
                date=date,
                defaults={
                    'instructor_id': course.instructor.id,
                    'total_enrollments': total_enrollments,
                    'active_enrollments': active_enrollments,
                    'completed_enrollments': completed_enrollments,
                    'dropped_enrollments': dropped_enrollments,
                    'avg_completion_rate': avg_completion_rate,
                    'avg_engagement_score': 100 - avg_engagement_score, # Invert risk score
                    'total_revenue': total_revenue,
                    'avg_revenue_per_student': avg_revenue_per_student,
                }
            )
            
            if not created:
                # Update existing analytics
                course_analytics.total_enrollments = total_enrollments
                course_analytics.active_enrollments = active_enrollments
                course_analytics.completed_enrollments = completed_enrollments
                course_analytics.dropped_enrollments = dropped_enrollments
                course_analytics.avg_completion_rate = avg_completion_rate
                course_analytics.avg_engagement_score = 100 - avg_engagement_score
                course_analytics.total_revenue = total_revenue
                course_analytics.avg_revenue_per_student = avg_revenue_per_student
                course_analytics.save()

    @staticmethod
    def process_instructor_analytics(tenant: Tenant, date: datetime.date = None):
        """Process and store instructor analytics for a specific date."""
        if date is None:
            date = timezone.now().date() - timedelta(days=1)
        
        # Get all instructors in the tenant
        instructors = User.objects.filter(
            role='instructor',
            courses__tenant=tenant
        ).distinct()
        
        for instructor in instructors:
            # Get instructor's courses
            courses = Course.objects.filter(instructor=instructor, tenant=tenant)
            
            total_courses = courses.count()
            published_courses = courses.filter(status='published').count()
            draft_courses = courses.filter(status='draft').count()
            
            # Get student metrics
            total_students = Enrollment.objects.filter(
                course__instructor=instructor,
                course__tenant=tenant
            ).count()
            
            active_students = Enrollment.objects.filter(
                course__instructor=instructor,
                course__tenant=tenant,
                status=Enrollment.Status.ACTIVE
            ).count()
            
            # Calculate new students (enrolled in last 30 days)
            new_students = Enrollment.objects.filter(
                course__instructor=instructor,
                course__tenant=tenant,
                enrolled_at__gte=date - timedelta(days=30)
            ).count()
            
            # Calculate performance metrics
            course_analytics = CourseAnalytics.objects.filter(
                instructor_id=instructor.id,
                tenant=tenant,
                date=date
            )
            
            avg_completion_rate = course_analytics.aggregate(
                avg_rate=Avg('avg_completion_rate')
            )['avg_rate'] or 0
            
            avg_engagement_rate = course_analytics.aggregate(
                avg_engagement=Avg('avg_engagement_score')
            )['avg_engagement'] or 0
            
            # Calculate revenue
            total_revenue = course_analytics.aggregate(
                total=Sum('total_revenue')
            )['total'] or 0
            
            monthly_revenue = total_revenue  # Simplified for demo
            avg_revenue_per_student = (
                total_revenue / total_students if total_students > 0 else 0
            )
            
            # Get or create instructor analytics
            instructor_analytics, created = InstructorAnalytics.objects.get_or_create(
                tenant=tenant,
                instructor_id=instructor.id,
                date=date,
                defaults={
                    'total_courses': total_courses,
                    'published_courses': published_courses,
                    'draft_courses': draft_courses,
                    'total_students': total_students,
                    'active_students': active_students,
                    'new_students': new_students,
                    'avg_completion_rate': avg_completion_rate,
                    'avg_engagement_rate': avg_engagement_rate,
                    'total_revenue': total_revenue,
                    'monthly_revenue': monthly_revenue,
                    'avg_revenue_per_student': avg_revenue_per_student,
                }
            )
            
            if not created:
                # Update existing analytics
                instructor_analytics.total_courses = total_courses
                instructor_analytics.published_courses = published_courses
                instructor_analytics.draft_courses = draft_courses
                instructor_analytics.total_students = total_students
                instructor_analytics.active_students = active_students
                instructor_analytics.new_students = new_students
                instructor_analytics.avg_completion_rate = avg_completion_rate
                instructor_analytics.avg_engagement_rate = avg_engagement_rate
                instructor_analytics.total_revenue = total_revenue
                instructor_analytics.monthly_revenue = monthly_revenue
                instructor_analytics.avg_revenue_per_student = avg_revenue_per_student
                instructor_analytics.save()

    @staticmethod
    def generate_ai_insights(tenant: Tenant, instructor_id: uuid.UUID, date: datetime.date = None):
        """Generate AI insights for an instructor."""
        if date is None:
            date = timezone.now().date()
        
        # Get instructor analytics
        instructor_analytics = InstructorAnalytics.objects.filter(
            tenant=tenant,
            instructor_id=instructor_id,
            date__lte=date
        ).order_by('-date')[:30]  # Last 30 days
        
        if not instructor_analytics.exists():
            return
        
        # Generate insights (simplified AI simulation)
        key_insights = []
        recommendations = []
        anomalies = []
        
        latest_analytics = instructor_analytics.first()
        
        # Analyze trends
        if instructor_analytics.count() > 1:
            previous_analytics = instructor_analytics[1]
            
            # Student growth analysis
            student_growth = latest_analytics.total_students - previous_analytics.total_students
            if student_growth > 0:
                key_insights.append({
                    'type': 'positive',
                    'title': 'Student Growth',
                    'description': f'You gained {student_growth} new students',
                    'priority': 'high'
                })
            elif student_growth < -5:
                key_insights.append({
                    'type': 'negative',
                    'title': 'Student Decline',
                    'description': f'You lost {abs(student_growth)} students',
                    'priority': 'high'
                })
            
            # Engagement analysis
            engagement_change = latest_analytics.avg_engagement_rate - previous_analytics.avg_engagement_rate
            if engagement_change > 5:
                key_insights.append({
                    'type': 'positive',
                    'title': 'Improved Engagement',
                    'description': f'Student engagement increased by {engagement_change:.1f}%',
                    'priority': 'medium'
                })
            elif engagement_change < -5:
                key_insights.append({
                    'type': 'warning',
                    'title': 'Declining Engagement',
                    'description': f'Student engagement decreased by {abs(engagement_change):.1f}%',
                    'priority': 'high'
                })
                recommendations.append({
                    'title': 'Boost Engagement',
                    'description': 'Consider adding interactive elements or updating content',
                    'priority': 'high'
                })
        
        # Completion rate analysis
        if latest_analytics.avg_completion_rate < 60:
            key_insights.append({
                'type': 'warning',
                'title': 'Low Completion Rate',
                'description': f'Average completion rate is {latest_analytics.avg_completion_rate:.1f}%',
                'priority': 'high'
            })
            recommendations.append({
                'title': 'Improve Course Structure',
                'description': 'Consider breaking down complex topics into smaller modules',
                'priority': 'high'
            })
        
        # Revenue analysis
        if latest_analytics.total_revenue > 0:
            key_insights.append({
                'type': 'positive',
                'title': 'Revenue Performance',
                'description': f'Generated ${latest_analytics.total_revenue:.2f} in revenue',
                'priority': 'medium'
            })
        
        # Create or update AI insights
        ai_insights, created = AIInsights.objects.get_or_create(
            tenant=tenant,
            instructor_id=instructor_id,
            date=date,
            defaults={
                'key_insights': key_insights,
                'recommendations': recommendations,
                'anomalies': anomalies,
                'confidence_score': 85.0,  # Simulated confidence
                'ai_model': 'analytics_v1',
                'model_version': '1.0'
            }
        )
        
        if not created:
            ai_insights.key_insights = key_insights
            ai_insights.recommendations = recommendations
            ai_insights.anomalies = anomalies
            ai_insights.confidence_score = 85.0
            ai_insights.save()

    @staticmethod
    def generate_predictive_analytics(tenant: Tenant, instructor_id: uuid.UUID, date: datetime.date = None):
        """Generate predictive analytics for an instructor."""
        if date is None:
            date = timezone.now().date()
        
        # Get students at risk
        students_at_risk = []
        high_risk_students = StudentEngagementMetric.objects.filter(
            tenant=tenant,
            course_id__in=Course.objects.filter(
                instructor_id=instructor_id,
                tenant=tenant
            ).values_list('id', flat=True),
            risk_score__gte=70,
            date=date
        ).select_related('user')
        
        for student_metric in high_risk_students:
            students_at_risk.append({
                'user_id': str(student_metric.user.id),
                'name': f"{student_metric.user.first_name} {student_metric.user.last_name}",
                'email': student_metric.user.email,
                'risk_score': float(student_metric.risk_score),
                'risk_factors': student_metric.risk_factors,
                'course_id': str(student_metric.course_id)
            })
        
        # Generate course recommendations (simplified)
        course_recommendations = [
            {
                'type': 'content_update',
                'title': 'Update Course Content',
                'description': 'Consider updating outdated content in your courses',
                'confidence': 75.0
            },
            {
                'type': 'new_course',
                'title': 'Create Advanced Course',
                'description': 'High demand for advanced topics in your subject area',
                'confidence': 60.0
            }
        ]
        
        # Generate revenue forecast (simplified)
        revenue_forecast = []
        current_revenue = InstructorAnalytics.objects.filter(
            tenant=tenant,
            instructor_id=instructor_id,
            date__lte=date
        ).aggregate(avg_revenue=Avg('monthly_revenue'))['avg_revenue'] or 0
        
        for i in range(1, 7):  # 6 months forecast
            forecast_date = date + timedelta(days=30*i)
            # Simple growth model
            growth_factor = 1 + (0.05 * i)  # 5% growth per month
            forecasted_revenue = current_revenue * growth_factor
            
            revenue_forecast.append({
                'date': forecast_date.isoformat(),
                'predicted_revenue': float(forecasted_revenue),
                'confidence': max(90 - (i * 10), 50)  # Decreasing confidence
            })
        
        # Create or update predictive analytics
        predictive_analytics, created = PredictiveAnalytics.objects.get_or_create(
            tenant=tenant,
            instructor_id=instructor_id,
            prediction_date=date,
            defaults={
                'students_at_risk': students_at_risk,
                'course_recommendations': course_recommendations,
                'revenue_forecast': revenue_forecast,
                'prediction_confidence': 82.5,
                'model_version': '1.0'
            }
        )
        
        if not created:
            predictive_analytics.students_at_risk = students_at_risk
            predictive_analytics.course_recommendations = course_recommendations
            predictive_analytics.revenue_forecast = revenue_forecast
            predictive_analytics.prediction_confidence = 82.5
            predictive_analytics.save()

    @staticmethod
    def update_real_time_metrics(tenant: Tenant, instructor_id: uuid.UUID):
        """Update real-time metrics for an instructor."""
        now = timezone.now()
        last_15_min = now - timedelta(minutes=15)
        last_hour = now - timedelta(hours=1)
        
        # Get instructor's course IDs
        instructor_course_ids = list(Course.objects.filter(
            instructor_id=instructor_id,
            tenant=tenant
        ).values_list('id', flat=True))
        
        # Get current active users (users with events in last 15 minutes)
        active_users = Event.objects.filter(
            tenant=tenant,
            created_at__gte=last_15_min,
            context_data__has_key='course_id'
        ).filter(
            context_data__course_id__in=[str(cid) for cid in instructor_course_ids]
        ).values('user_id').distinct().count()
        
        # Get current sessions (SESSION_START without SESSION_END in last hour)
        current_sessions = Event.objects.filter(
            tenant=tenant,
            event_type='SESSION_START',
            created_at__gte=last_hour
        ).count()
        
        # Calculate live engagement rate
        total_enrolled = Enrollment.objects.filter(
            course__instructor_id=instructor_id,
            course__tenant=tenant,
            status=Enrollment.Status.ACTIVE
        ).count()
        
        live_engagement_rate = (
            (active_users / total_enrolled * 100) if total_enrolled > 0 else 0
        )
        
        # Get current course views from events
        current_course_views = Event.objects.filter(
            tenant=tenant,
            event_type='COURSE_VIEW',
            created_at__gte=last_15_min,
            context_data__course_id__in=[str(cid) for cid in instructor_course_ids]
        ).count()
        
        # Get current video watches from events
        current_video_watches = Event.objects.filter(
            tenant=tenant,
            event_type='VIDEO_WATCH',
            created_at__gte=last_15_min,
            context_data__course_id__in=[str(cid) for cid in instructor_course_ids]
        ).count()
        
        # Get current quiz attempts from events
        current_quiz_attempts = Event.objects.filter(
            tenant=tenant,
            event_type='QUIZ_ATTEMPT',
            created_at__gte=last_15_min,
            context_data__course_id__in=[str(cid) for cid in instructor_course_ids]
        ).count()
        
        # Create real-time metrics with actual data
        # Note: server_health and response_time should ideally come from 
        # infrastructure monitoring, defaulting to reasonable values
        RealTimeMetrics.objects.create(
            tenant=tenant,
            instructor_id=instructor_id,
            active_users=active_users,
            current_sessions=current_sessions,
            live_engagement_rate=live_engagement_rate,
            server_health=100.0,  # Default healthy state
            response_time=0,  # Would come from actual monitoring
            current_course_views=current_course_views,
            current_video_watches=current_video_watches,
            current_quiz_attempts=current_quiz_attempts
        )


class ReportGenerationError(Exception):
    pass


class ReportGeneratorService:
    """Service for generating comprehensive analytics reports."""

    @staticmethod
    def generate_report_data(
        report: Report, filters: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        """Generates data based on the report definition and filters."""
        filters = filters or {}
        slug = report.slug
        tenant = (
            report.tenant
        )  # Use tenant from report definition (can be None for system)

        logger.info(
            f"Generating report data for slug: {slug}, tenant: {tenant.id if tenant else 'System'}, filters: {filters}"
        )

        # --- Dispatch to specific report generation methods ---
        try:
            if slug == "course-completion-rates" or slug == "course-completion":
                data = ReportGeneratorService._generate_course_completion_report(
                    tenant, filters
                )
            elif slug == "user-activity-summary":
                data = ReportGeneratorService._generate_user_activity_report(
                    tenant, filters
                )
            elif slug == "assessment-average-scores" or slug == "assessment-results":
                data = ReportGeneratorService._generate_assessment_scores_report(
                    tenant, filters
                )
            elif slug == "student-progress":
                data = ReportGeneratorService._generate_student_progress_report(
                    tenant, filters
                )
            # Add more report types here...
            # elif slug == 'content-item-popularity':
            #     data = ReportGeneratorService._generate_content_popularity_report(tenant, filters)
            elif slug == "instructor-dashboard":
                data = ReportGeneratorService._generate_instructor_dashboard_report(tenant, filters)
            elif slug == "student-engagement":
                data = ReportGeneratorService._generate_student_engagement_report(tenant, filters)
            elif slug == "course-performance":
                data = ReportGeneratorService._generate_course_performance_report(tenant, filters)
            elif slug == "predictive-insights":
                data = ReportGeneratorService._generate_predictive_insights_report(tenant, filters)
            elif slug == "ai-recommendations":
                data = ReportGeneratorService._generate_ai_recommendations_report(tenant, filters)
            elif slug == "real-time-metrics":
                data = ReportGeneratorService._generate_real_time_metrics_report(tenant, filters)
            else:
                raise ReportGenerationError(
                    f"Report generator not found for slug: {slug}"
                )
        except ObjectDoesNotExist as e:
            logger.warning(f"Object not found during report generation for {slug}: {e}")
            raise ReportGenerationError(
                f"Required data not found for report {slug}: {e}"
            ) from e
        except Exception as e:
            logger.error(
                f"Unexpected error during report generation logic for {slug}: {e}",
                exc_info=True,
            )
            raise ReportGenerationError(
                f"Internal error generating report {slug}."
            ) from e

        return {
            "report_slug": slug,
            "report_name": report.name,
            "generated_at": timezone.now().isoformat(),
            "filters_applied": filters,
            "data": data,
            # Add summary info if needed by the specific generator method
        }

    # --- Specific Report Generation Methods ---

    @staticmethod
    def _apply_common_filters(
        queryset, filters: Dict[str, Any], date_field="created_at"
    ):
        """Applies common filters like date range."""
        start_date_str = filters.get("start_date")
        end_date_str = filters.get("end_date")
        tz = timezone.get_current_timezone()  # Use current timezone

        if start_date_str:
            try:
                # Assume YYYY-MM-DD format
                start_date = tz.localize(datetime.strptime(start_date_str, "%Y-%m-%d"))
                date_filter_gte = {f"{date_field}__gte": start_date}
                queryset = queryset.filter(**date_filter_gte)
            except (ValueError, TypeError):
                logger.warning(
                    f"Invalid start_date format: {start_date_str}. Expected YYYY-MM-DD."
                )
                raise ReportGenerationError(
                    f"Invalid start date format: '{start_date_str}'. Use YYYY-MM-DD."
                )
        if end_date_str:
            try:
                # End date usually means up to the end of that day
                end_date = tz.localize(
                    datetime.strptime(end_date_str, "%Y-%m-%d")
                ) + timedelta(days=1)
                date_filter_lt = {f"{date_field}__lt": end_date}
                queryset = queryset.filter(**date_filter_lt)
            except (ValueError, TypeError):
                logger.warning(
                    f"Invalid end_date format: {end_date_str}. Expected YYYY-MM-DD."
                )
                raise ReportGenerationError(
                    f"Invalid end date format: '{end_date_str}'. Use YYYY-MM-DD."
                )

        # Add other common filters (user_id, course_id etc.) if applicable
        user_id = filters.get("user_id")
        course_id = filters.get("course_id")
        if user_id and hasattr(queryset.model, "user"):
            queryset = queryset.filter(user_id=user_id)
        # Be careful applying course_id filter generally, check model relationship
        if course_id:
            if hasattr(queryset.model, "course"):
                queryset = queryset.filter(course_id=course_id)
            elif hasattr(queryset.model, "assessment") and hasattr(
                AssessmentAttempt.assessment.field.related_model, "course"
            ):
                queryset = queryset.filter(assessment__course_id=course_id)
            # Add other relationships...

        return queryset

    @staticmethod
    def _generate_course_completion_report(
        tenant: Tenant | None, filters: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generates data for course completion rates."""
        # Apply instructor filter if provided - filter to only instructor's courses
        instructor_id = filters.get("instructor")
        
        # Base queryset for enrollments within the tenant (or all if tenant is None)
        enrollment_qs = Enrollment.objects.select_related("course")
        if tenant:
            enrollment_qs = enrollment_qs.filter(course__tenant=tenant)

        # Filter by instructor's courses if specified
        if instructor_id:
            enrollment_qs = enrollment_qs.filter(course__instructor_id=instructor_id)

        # Apply filters (e.g., date range on enrollment creation or completion?)
        # Let's filter by course publication date range for relevance? Or enrollment date?
        # Filtering by enrollment date seems more useful here.
        enrollment_qs = ReportGeneratorService._apply_common_filters(
            enrollment_qs, filters, date_field="enrolled_at"
        )

        # Filter by specific course if provided
        course_id = filters.get("course_id")
        if course_id:
            enrollment_qs = enrollment_qs.filter(course_id=course_id)

        # Aggregate completion status per course
        completion_data = (
            enrollment_qs.values("course_id", "course__title")  # Group by course
            .annotate(
                total_enrollments=Count("id"),
                completed_enrollments=Count(
                    "id", filter=Q(status=Enrollment.Status.COMPLETED)
                ),
            )
            .order_by("course__title")
        )

        # Format results
        report_data = []
        for item in completion_data:
            total = item["total_enrollments"]
            completed = item["completed_enrollments"]
            # Ensure Decimal conversion for accurate division
            rate = (
                (Decimal(completed) / Decimal(total) * 100) if total > 0 else Decimal(0)
            )
            report_data.append(
                {
                    "course_id": item["course_id"],
                    "course_title": item["course__title"],
                    "total_enrollments": total,
                    "completed_enrollments": completed,
                    "completion_rate": float(
                        rate.quantize(Decimal("0.01"))
                    ),  # Return as float for JSON
                }
            )
        return report_data

    @staticmethod
    def _generate_user_activity_report(
        tenant: Tenant | None, filters: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generates data summarizing user activity (logins, content views, last activity)."""
        # Query Events
        event_qs = Event.objects.select_related("user")
        if tenant:
            event_qs = event_qs.filter(tenant=tenant)

        # Apply common filters (date range on event timestamp 'created_at')
        event_qs = ReportGeneratorService._apply_common_filters(
            event_qs, filters, date_field="created_at"
        )

        user_id = filters.get("user_id")
        if user_id:
            event_qs = event_qs.filter(user_id=user_id)

        # Aggregate events per user
        activity_data = (
            event_qs.exclude(user=None)
            .values("user_id", "user__email", "user__first_name", "user__last_name")
            .annotate(
                login_count=Count("id", filter=Q(event_type="USER_LOGIN")),
                content_view_count=Count("id", filter=Q(event_type="CONTENT_VIEW")),
                course_complete_count=Count(
                    "id", filter=Q(event_type="COURSE_COMPLETE")
                ),
                assessment_submit_count=Count(
                    "id", filter=Q(event_type="ASSESSMENT_SUBMIT")
                ),
                last_activity=Max("created_at"),  # Use Max aggregation
            )
            .order_by("-last_activity")
        )  # Show most recently active first

        # Format results for JSON compatibility (dates to ISO strings)
        report_data = [
            {
                **item,
                "last_activity": (
                    item["last_activity"].isoformat() if item["last_activity"] else None
                ),
            }
            for item in activity_data
        ]
        return report_data

    @staticmethod
    def _generate_assessment_scores_report(
        tenant: Tenant | None, filters: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generates average scores and pass rates for assessments."""
        # Apply instructor filter if provided - filter to only instructor's courses
        instructor_id = filters.get("instructor")
        
        # Base queryset
        attempt_qs = AssessmentAttempt.objects.filter(
            status=AssessmentAttempt.AttemptStatus.GRADED  # Only graded attempts
        ).select_related("assessment", "assessment__course")

        if tenant:
            attempt_qs = attempt_qs.filter(assessment__course__tenant=tenant)

        # Filter by instructor's courses if specified
        if instructor_id:
            attempt_qs = attempt_qs.filter(assessment__course__instructor_id=instructor_id)

        # Apply filters (date range on attempt submission or grading?)
        # Let's use submission time (end_time)
        attempt_qs = ReportGeneratorService._apply_common_filters(
            attempt_qs, filters, date_field="end_time"
        )

        # Filter by specific course/assessment if provided
        course_id = filters.get("course_id")
        assessment_id = filters.get("assessment_id")
        if course_id:
            attempt_qs = attempt_qs.filter(assessment__course_id=course_id)
        if assessment_id:
            attempt_qs = attempt_qs.filter(assessment_id=assessment_id)

        # Aggregate scores per assessment
        score_data = (
            attempt_qs.values(
                "assessment_id", "assessment__title", "assessment__course__title"
            )
            .annotate(
                average_score=Avg(
                    "score", filter=Q(score__isnull=False)
                ),  # Calculate avg only on non-null scores
                attempt_count=Count("id"),
                pass_count=Count("id", filter=Q(is_passed=True)),
            )
            .order_by("assessment__course__title", "assessment__title")
        )

        # Format results
        report_data = []
        for item in score_data:
            total = item["attempt_count"]
            passed = item["pass_count"]
            # Ensure Decimal for calculation
            pass_rate = (
                (Decimal(passed) / Decimal(total) * 100) if total > 0 else Decimal(0)
            )
            avg_score = item["average_score"]
            report_data.append(
                {
                    "assessment_id": item["assessment_id"],
                    "assessment_title": item["assessment__title"],
                    "course_title": item["assessment__course__title"],
                    # Convert Decimal average score to float for JSON
                    "average_score": (
                        float(avg_score.quantize(Decimal("0.01")))
                        if avg_score is not None
                        else None
                    ),
                    "attempt_count": total,
                    "pass_rate": float(
                        pass_rate.quantize(Decimal("0.01"))
                    ),  # Return as float
                }
            )
        return report_data

    @staticmethod
    def _generate_student_progress_report(
        tenant: Tenant | None, filters: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generates data for student progress in courses."""
        # Apply instructor filter if provided - filter to only instructor's courses
        instructor_id = filters.get("instructor")

        # Base queryset for enrollments with related user and course data
        enrollment_qs = Enrollment.objects.select_related("user", "course")
        if tenant:
            enrollment_qs = enrollment_qs.filter(course__tenant=tenant)

        # Filter by instructor's courses if specified
        if instructor_id:
            enrollment_qs = enrollment_qs.filter(course__instructor_id=instructor_id)

        # Apply other filters (e.g., date range on enrollment)
        enrollment_qs = ReportGeneratorService._apply_common_filters(
            enrollment_qs, filters, date_field="enrolled_at"
        )

        # Filter by specific user or course if provided
        user_id = filters.get("user_id")
        course_id = filters.get("course_id")
        if user_id:
            enrollment_qs = enrollment_qs.filter(user_id=user_id)
        if course_id:
            enrollment_qs = enrollment_qs.filter(course_id=course_id)

        # Get individual enrollments with progress details
        enrollments = enrollment_qs.order_by("course__title", "user__last_name", "user__first_name")

        # Format results
        report_data = []
        for enrollment in enrollments:
            report_data.append({
                "user_id": str(enrollment.user.id),
                "user_email": enrollment.user.email,
                "user_first_name": enrollment.user.first_name,
                "user_last_name": enrollment.user.last_name,
                "course_id": str(enrollment.course.id),
                "course_title": enrollment.course.title,
                "enrollment_date": enrollment.enrolled_at.isoformat() if enrollment.enrolled_at else None,
                "status": enrollment.status,
                "progress_percentage": getattr(enrollment, 'progress', 0),  # Use progress field if it exists
                "completion_date": enrollment.completed_at.isoformat() if getattr(enrollment, 'completed_at', None) else None,
            })

        return report_data

    @staticmethod
    def _generate_instructor_dashboard_report(
        tenant: Tenant | None, filters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate comprehensive instructor dashboard data."""
        instructor_id = filters.get("instructor_id")
        if not instructor_id:
            raise ReportGenerationError("instructor_id is required for instructor dashboard")
        
        # Get latest analytics
        latest_analytics = InstructorAnalytics.objects.filter(
            tenant=tenant,
            instructor_id=instructor_id
        ).order_by('-date').first()
        
        if not latest_analytics:
            return {"error": "No analytics data available"}
        
        # Get AI insights
        ai_insights = AIInsights.objects.filter(
            tenant=tenant,
            instructor_id=instructor_id
        ).order_by('-date').first()
        
        # Get predictive analytics
        predictive_analytics = PredictiveAnalytics.objects.filter(
            tenant=tenant,
            instructor_id=instructor_id
        ).order_by('-prediction_date').first()
        
        # Get real-time metrics
        real_time_metrics = RealTimeMetrics.objects.filter(
            tenant=tenant,
            instructor_id=instructor_id
        ).order_by('-timestamp').first()
        
        return {
            "overview": {
                "total_courses": latest_analytics.total_courses,
                "total_students": latest_analytics.total_students,
                "active_students": latest_analytics.active_students,
                "total_revenue": float(latest_analytics.total_revenue),
                "avg_completion_rate": float(latest_analytics.avg_completion_rate),
                "avg_engagement_rate": float(latest_analytics.avg_engagement_rate)
            },
            "ai_insights": {
                "key_insights": ai_insights.key_insights if ai_insights else [],
                "recommendations": ai_insights.recommendations if ai_insights else [],
                "confidence_score": float(ai_insights.confidence_score) if ai_insights else 0
            },
            "predictive_analytics": {
                "students_at_risk": predictive_analytics.students_at_risk if predictive_analytics else [],
                "revenue_forecast": predictive_analytics.revenue_forecast if predictive_analytics else [],
                "course_recommendations": predictive_analytics.course_recommendations if predictive_analytics else []
            },
            "real_time": {
                "active_users": real_time_metrics.active_users if real_time_metrics else 0,
                "current_sessions": real_time_metrics.current_sessions if real_time_metrics else 0,
                "live_engagement_rate": float(real_time_metrics.live_engagement_rate) if real_time_metrics else 0,
                "server_health": float(real_time_metrics.server_health) if real_time_metrics else 100
            }
        }

    # ...existing methods...


class DataProcessorService:
    """Service for background data processing and aggregation."""

    @staticmethod
    def process_daily_analytics(tenant: Tenant, date: datetime.date = None):
        """Process all daily analytics for a tenant."""
        if date is None:
            date = timezone.now().date() - timedelta(days=1)
        
        logger.info(f"Processing daily analytics for {tenant.name} on {date}")
        
        try:
            # Process student engagement metrics
            AnalyticsService.process_student_engagement_metrics(tenant, date)
            
            # Process course analytics
            AnalyticsService.process_course_analytics(tenant, date)
            
            # Process instructor analytics
            AnalyticsService.process_instructor_analytics(tenant, date)
            
            # Generate AI insights for all instructors
            instructors = User.objects.filter(
                role='instructor',
                courses__tenant=tenant
            ).distinct()
            
            for instructor in instructors:
                AnalyticsService.generate_ai_insights(tenant, instructor.id, date)
                AnalyticsService.generate_predictive_analytics(tenant, instructor.id, date)
            
            logger.info(f"Successfully processed daily analytics for {tenant.name}")
            
        except Exception as e:
            logger.error(f"Error processing daily analytics for {tenant.name}: {e}", exc_info=True)
            raise

    @staticmethod
    def process_real_time_metrics(tenant: Tenant):
        """Process real-time metrics for all instructors in a tenant."""
        instructors = User.objects.filter(
            role='instructor',
            courses__tenant=tenant
        ).distinct()
        
        for instructor in instructors:
            AnalyticsService.update_real_time_metrics(tenant, instructor.id)

    @staticmethod
    def aggregate_daily_metrics():
        """Process daily analytics for all tenants."""
        tenants = Tenant.objects.filter(is_active=True)
        
        for tenant in tenants:
            try:
                DataProcessorService.process_daily_analytics(tenant)
            except Exception as e:
                logger.error(f"Failed to process analytics for tenant {tenant.name}: {e}")
                continue


class ExportService:
    """Service for exporting report data to different formats."""

    @staticmethod
    def export_report_to_csv(report_data: List[Dict[str, Any]]) -> str:
        """Converts a list of report data dictionaries to a CSV string."""
        if not report_data:
            return ""

        output = StringIO()
        # Use the keys from the first dictionary as headers, maintain order if possible
        # Using list(dict.keys()) preserves insertion order in Python 3.7+
        headers = list(report_data[0].keys()) if report_data else []
        if not headers:
            return ""  # No headers if data is empty list of empty dicts

        writer = csv.DictWriter(output, fieldnames=headers, quoting=csv.QUOTE_MINIMAL)

        writer.writeheader()
        writer.writerows(report_data)

        return output.getvalue()

    @staticmethod
    def export_report_to_json(report_data: List[Dict[str, Any]]) -> str:
        """Converts report data to a JSON string, handling specific types."""

        def default_serializer(obj):
            if isinstance(obj, Decimal):
                # Convert Decimal to float for JSON compatibility
                return float(obj)
            if isinstance(obj, (datetime, models.DateField, models.DateTimeField)):
                # Format dates as ISO 8601 strings
                return obj.isoformat()
            if isinstance(obj, uuid.UUID):
                return str(obj)
            # Let default JSON encoder handle built-in types, raise error for others
            raise TypeError(f"Type {type(obj)} not serializable for JSON export")

        try:
            return json.dumps(report_data, indent=2, default=default_serializer)
        except TypeError as e:
            logger.error(f"JSON serialization error during export: {e}")
            # Fallback or raise a specific export error
            raise ReportGenerationError(
                f"Could not serialize report data to JSON: {e}"
            ) from e


class VisualizationService:
    """Service stub for generating visualization configurations."""

    @staticmethod
    def get_chart_config(
        report_slug: str, data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Returns a configuration object for a frontend charting library."""
        logger.debug(f"Generating chart config for report: {report_slug}")
        # Example config generation based on slug
        try:
            if report_slug == "course-completion-rates" and data:
                return {
                    "type": "bar",
                    "data": {
                        "labels": [item.get("course_title", "N/A") for item in data],
                        "datasets": [
                            {
                                "label": "Completion Rate (%)",
                                "data": [
                                    item.get("completion_rate", 0) for item in data
                                ],
                                "backgroundColor": "rgba(75, 192, 192, 0.6)",  # Example color
                                "borderColor": "rgba(75, 192, 192, 1)",
                                "borderWidth": 1,
                            }
                        ],
                    },
                    "options": {
                        "responsive": True,
                        "maintainAspectRatio": False,
                        "scales": {
                            "y": {
                                "beginAtZero": True,
                                "max": 100,
                                "title": {
                                    "display": True,
                                    "text": "Completion Rate (%)",
                                },
                            },
                            "x": {"title": {"display": True, "text": "Course"}},
                        },
                    },
                }
            elif report_slug == "user-activity-summary" and data:
                # Could be a table, or maybe a scatter plot of logins vs content views?
                # Returning data suitable for a table representation
                pass  # Fall through to default table config
            elif report_slug == "assessment-average-scores" and data:
                return {
                    "type": "bar",  # Or grouped bar chart
                    "data": {
                        "labels": [
                            item.get("assessment_title", "N/A") for item in data
                        ],
                        "datasets": [
                            {
                                "label": "Average Score (%)",  # Assuming score is percentage or needs conversion
                                "data": [
                                    item.get("average_score", 0) for item in data
                                ],  # Needs score interpretation
                                "backgroundColor": "rgba(153, 102, 255, 0.6)",
                                "borderColor": "rgba(153, 102, 255, 1)",
                                "borderWidth": 1,
                                "yAxisID": "yScore",
                            },
                            {
                                "label": "Pass Rate (%)",
                                "data": [item.get("pass_rate", 0) for item in data],
                                "backgroundColor": "rgba(255, 159, 64, 0.6)",
                                "borderColor": "rgba(255, 159, 64, 1)",
                                "borderWidth": 1,
                                "yAxisID": "yRate",
                            },
                        ],
                    },
                    "options": {
                        "responsive": True,
                        "maintainAspectRatio": False,
                        "scales": {
                            "yScore": {
                                "type": "linear",
                                "position": "left",
                                "beginAtZero": True,
                                "max": 100,
                                "title": {"display": True, "text": "Average Score (%)"},
                            },
                            "yRate": {
                                "type": "linear",
                                "position": "right",
                                "beginAtZero": True,
                                "max": 100,
                                "title": {"display": True, "text": "Pass Rate (%)"},
                                "grid": {"drawOnChartArea": False},
                            },
                            "x": {"title": {"display": True, "text": "Assessment"}},
                        },
                    },
                }
            # Add more chart configurations for other reports...

        except Exception as e:
            logger.error(
                f"Error creating chart config for {report_slug}: {e}", exc_info=True
            )

        # Default to table configuration if no specific chart defined or error occurs
        logger.warning(
            f"No specific chart config found for report {report_slug}, defaulting to table."
        )
        headers = list(data[0].keys()) if data else []
        return {
            "type": "table",
            "data": data,
            "columns": [
                {"key": h, "header": h.replace("_", " ").title()} for h in headers
            ],  # Basic column generation
        }


class ComprehensiveAnalyticsService:
    """Service for comprehensive analytics data processing and aggregation."""

    @staticmethod
    def get_instructor_dashboard_data(instructor_id: str, tenant: Optional[Tenant] = None) -> Dict[str, Any]:
        """
        Get comprehensive instructor dashboard data including all analytics.
        """
        try:
            instructor_uuid = uuid.UUID(instructor_id)
        except ValueError:
            raise ValueError(f"Invalid instructor ID format: {instructor_id}")

        # Get current date for filtering
        today = timezone.now().date()
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)

        # Get basic course statistics
        course_stats = ComprehensiveAnalyticsService._get_course_statistics(
            instructor_uuid, tenant
        )

        # Get student analytics
        student_analytics = ComprehensiveAnalyticsService._get_student_analytics(
            instructor_uuid, tenant
        )

        # Get performance metrics
        performance_metrics = ComprehensiveAnalyticsService._get_performance_metrics(
            instructor_uuid, tenant
        )

        # Get AI insights
        ai_insights = ComprehensiveAnalyticsService._get_ai_insights(
            instructor_uuid, tenant
        )

        # Get predictive analytics
        predictive_data = ComprehensiveAnalyticsService._get_predictive_analytics(
            instructor_uuid, tenant
        )

        # Get real-time metrics
        realtime_metrics = ComprehensiveAnalyticsService._get_realtime_metrics(
            instructor_uuid, tenant
        )

        # Get learning efficiency data
        learning_efficiency = ComprehensiveAnalyticsService._get_learning_efficiency(
            instructor_uuid, tenant
        )

        # Get social learning metrics
        social_metrics = ComprehensiveAnalyticsService._get_social_learning_metrics(
            instructor_uuid, tenant
        )

        # Get revenue and financial data
        revenue_data = ComprehensiveAnalyticsService._get_revenue_analytics(
            instructor_uuid, tenant
        )

        # Get engagement trends
        engagement_trends = ComprehensiveAnalyticsService._get_engagement_trends(
            instructor_uuid, tenant
        )

        return {
            "instructor_id": instructor_id,
            "generated_at": timezone.now().isoformat(),
            "course_statistics": course_stats,
            "student_analytics": student_analytics,
            "performance_metrics": performance_metrics,
            "ai_insights": ai_insights,
            "predictive_analytics": predictive_data,
            "realtime_metrics": realtime_metrics,
            "learning_efficiency": learning_efficiency,
            "social_learning": social_metrics,
            "revenue_analytics": revenue_data,
            "engagement_trends": engagement_trends,
        }

    @staticmethod
    def _get_course_statistics(instructor_id: uuid.UUID, tenant: Optional[Tenant]) -> Dict[str, Any]:
        """Get basic course statistics for an instructor."""
        course_qs = Course.objects.filter(instructor_id=instructor_id)
        if tenant:
            course_qs = course_qs.filter(tenant=tenant)

        total_courses = course_qs.count()
        published_courses = course_qs.filter(is_published=True).count()
        draft_courses = total_courses - published_courses

        # Get enrollment statistics
        enrollment_stats = Enrollment.objects.filter(
            course__instructor_id=instructor_id
        )
        if tenant:
            enrollment_stats = enrollment_stats.filter(course__tenant=tenant)

        total_enrollments = enrollment_stats.count()
        active_enrollments = enrollment_stats.filter(
            status=Enrollment.Status.ACTIVE
        ).count()
        completed_enrollments = enrollment_stats.filter(
            status=Enrollment.Status.COMPLETED
        ).count()

        return {
            "total_courses": total_courses,
            "published_courses": published_courses,
            "draft_courses": draft_courses,
            "total_enrollments": total_enrollments,
            "active_enrollments": active_enrollments,
            "completed_enrollments": completed_enrollments,
            "completion_rate": (
                (completed_enrollments / total_enrollments * 100) 
                if total_enrollments > 0 else 0
            ),
        }

    @staticmethod
    def _get_student_analytics(instructor_id: uuid.UUID, tenant: Optional[Tenant]) -> Dict[str, Any]:
        """Get student analytics for an instructor."""
        today = timezone.now().date()
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)

        # Get unique students across all instructor's courses
        student_qs = User.objects.filter(
            enrollments__course__instructor_id=instructor_id
        ).distinct()
        if tenant:
            student_qs = student_qs.filter(enrollments__course__tenant=tenant)

        total_students = student_qs.count()

        # Get recent activity
        recent_activity = Event.objects.filter(
            user__in=student_qs,
            created_at__gte=timezone.now() - timedelta(days=7)
        )
        if tenant:
            recent_activity = recent_activity.filter(tenant=tenant)

        active_students = recent_activity.values('user_id').distinct().count()

        # Get new students (enrolled in the last 30 days)
        new_students = Enrollment.objects.filter(
            course__instructor_id=instructor_id,
            enrolled_at__gte=timezone.now() - timedelta(days=30)
        )
        if tenant:
            new_students = new_students.filter(course__tenant=tenant)
        
        new_students_count = new_students.values('user_id').distinct().count()

        # Get at-risk students (simple heuristic: no activity in 7 days)
        at_risk_students = student_qs.exclude(
            id__in=recent_activity.values('user_id')
        ).count()

        return {
            "total_students": total_students,
            "active_students": active_students,
            "new_students": new_students_count,
            "at_risk_students": at_risk_students,
            "activity_rate": (
                (active_students / total_students * 100) 
                if total_students > 0 else 0
            ),
        }

    @staticmethod
    def _get_performance_metrics(instructor_id: uuid.UUID, tenant: Optional[Tenant]) -> Dict[str, Any]:
        """Get performance metrics for an instructor's courses."""
        # Get assessments for instructor's courses
        assessments = AssessmentAttempt.objects.filter(
            assessment__course__instructor_id=instructor_id,
            status=AssessmentAttempt.AttemptStatus.GRADED
        )
        if tenant:
            assessments = assessments.filter(assessment__course__tenant=tenant)

        avg_score = assessments.aggregate(avg_score=Avg('score'))['avg_score'] or 0
        pass_rate = assessments.filter(is_passed=True).count()
        total_attempts = assessments.count()
        
        pass_percentage = (pass_rate / total_attempts * 100) if total_attempts > 0 else 0

        # Get course ratings from CourseAnalytics model
        course_analytics = CourseAnalytics.objects.filter(
            instructor_id=instructor_id
        )
        if tenant:
            course_analytics = course_analytics.filter(tenant=tenant)
        
        rating_data = course_analytics.aggregate(
            avg_rating=Avg('avg_rating'),
            total_reviews=Sum('total_reviews')
        )
        
        avg_rating = float(rating_data['avg_rating']) if rating_data['avg_rating'] else 0
        total_reviews = rating_data['total_reviews'] or 0

        return {
            "average_assessment_score": float(avg_score),
            "assessment_pass_rate": pass_percentage,
            "total_assessment_attempts": total_attempts,
            "average_course_rating": round(avg_rating, 2),
            "total_reviews": total_reviews,
        }

    @staticmethod
    def _get_ai_insights(instructor_id: uuid.UUID, tenant: Optional[Tenant]) -> Dict[str, Any]:
        """Get AI-generated insights for an instructor."""
        # Query the AIInsights model for stored insights
        today = timezone.now().date()
        
        ai_insights_query = AIInsights.objects.filter(
            instructor_id=instructor_id,
            date__lte=today
        ).order_by('-date')
        
        if tenant:
            ai_insights_query = ai_insights_query.filter(tenant=tenant)
        
        ai_insights = ai_insights_query.first()
        
        if ai_insights:
            return {
                "key_insights": ai_insights.key_insights or [],
                "recommendations": ai_insights.recommendations or [],
                "anomalies": ai_insights.anomalies or [],
                "confidence_score": float(ai_insights.confidence_score) if ai_insights.confidence_score else 0
            }
        
        # If no stored insights, return empty structure
        return {
            "key_insights": [],
            "recommendations": [],
            "anomalies": [],
            "confidence_score": 0
        }

    @staticmethod
    def _get_predictive_analytics(instructor_id: uuid.UUID, tenant: Optional[Tenant]) -> Dict[str, Any]:
        """Get predictive analytics for an instructor."""
        today = timezone.now().date()
        
        # Query the PredictiveAnalytics model for stored predictions
        predictive_query = PredictiveAnalytics.objects.filter(
            instructor_id=instructor_id,
            prediction_date__lte=today
        ).order_by('-prediction_date')
        
        if tenant:
            predictive_query = predictive_query.filter(tenant=tenant)
        
        predictive_data = predictive_query.first()
        
        # Get students at risk from StudentEngagementMetric
        instructor_courses = Course.objects.filter(instructor_id=instructor_id)
        if tenant:
            instructor_courses = instructor_courses.filter(tenant=tenant)
        
        course_ids = list(instructor_courses.values_list('id', flat=True))
        
        # Find students with high risk scores
        at_risk_students = StudentEngagementMetric.objects.filter(
            course_id__in=course_ids,
            risk_score__gte=60  # Risk threshold
        ).order_by('-risk_score')[:10]
        
        if tenant:
            at_risk_students = at_risk_students.filter(tenant=tenant)
        
        students_at_risk = []
        for student_metric in at_risk_students:
            students_at_risk.append({
                "student_id": str(student_metric.user_id),
                "student_name": student_metric.user.get_full_name() or student_metric.user.email,
                "risk_score": float(student_metric.risk_score),
                "risk_factors": student_metric.risk_factors or [],
                "course_id": str(student_metric.course_id)
            })
        
        # Build response from stored predictive data or defaults
        if predictive_data:
            return {
                "students_at_risk": students_at_risk,
                "revenue_forecast": predictive_data.revenue_forecast or {
                    "next_month": 0,
                    "next_quarter": 0,
                    "growth_prediction": 0
                },
                "enrollment_trends": predictive_data.trends_analysis or {
                    "predicted_next_month": 0,
                    "trend": "stable",
                    "confidence": float(predictive_data.prediction_confidence)
                },
                "content_recommendations": predictive_data.course_recommendations or []
            }
        
        # Return structure with real students at risk but empty forecasts if no stored predictions
        return {
            "students_at_risk": students_at_risk,
            "revenue_forecast": {
                "next_month": 0,
                "next_quarter": 0,
                "growth_prediction": 0
            },
            "enrollment_trends": {
                "predicted_next_month": 0,
                "trend": "stable",
                "confidence": 0
            },
            "content_recommendations": []
        }

    @staticmethod
    def _get_realtime_metrics(instructor_id: uuid.UUID, tenant: Optional[Tenant]) -> Dict[str, Any]:
        """Get real-time metrics for an instructor."""
        # Get current active users from recent events
        now = timezone.now()
        last_hour = now - timedelta(hours=1)
        
        instructor_courses = Course.objects.filter(instructor_id=instructor_id)
        if tenant:
            instructor_courses = instructor_courses.filter(tenant=tenant)
        course_ids = list(instructor_courses.values_list('id', flat=True))
        
        recent_events = Event.objects.filter(
            created_at__gte=last_hour,
            context_data__course_id__in=course_ids
        )
        if tenant:
            recent_events = recent_events.filter(tenant=tenant)

        active_users = recent_events.values('user_id').distinct().count()
        current_sessions = recent_events.filter(
            event_type='SESSION_START'
        ).count()
        
        # Get current activity counts from recent events
        current_course_views = recent_events.filter(event_type='COURSE_VIEW').count()
        current_video_watches = recent_events.filter(event_type__in=['VIDEO_WATCH', 'VIDEO_COMPLETE']).count()
        current_quiz_attempts = recent_events.filter(event_type='QUIZ_ATTEMPT').count()
        
        # Calculate live engagement rate based on active users vs total enrolled
        total_enrolled = Enrollment.objects.filter(
            course__in=instructor_courses,
            status=Enrollment.Status.ACTIVE
        ).values('user_id').distinct().count()
        
        live_engagement_rate = 0
        if total_enrolled > 0:
            live_engagement_rate = (active_users / total_enrolled) * 100
        
        # Check for stored real-time metrics (server health, response time would come from infrastructure monitoring)
        realtime_record = RealTimeMetrics.objects.filter(
            instructor_id=instructor_id,
            timestamp__gte=last_hour
        ).order_by('-timestamp').first()
        
        server_health = 100.0  # Default healthy
        response_time = 0  # Would come from infrastructure monitoring
        
        if realtime_record:
            server_health = float(realtime_record.server_health)
            response_time = realtime_record.response_time

        return {
            "active_users": active_users,
            "current_sessions": current_sessions,
            "live_engagement_rate": round(live_engagement_rate, 2),
            "server_health": server_health,
            "response_time": response_time,
            "current_course_views": current_course_views,
            "current_video_watches": current_video_watches,
            "current_quiz_attempts": current_quiz_attempts,
        }

    @staticmethod
    def _get_learning_efficiency(instructor_id: uuid.UUID, tenant: Optional[Tenant]) -> Dict[str, Any]:
        """Get learning efficiency metrics for an instructor."""
        today = timezone.now().date()
        
        # Query the LearningEfficiency model for stored efficiency data
        efficiency_query = LearningEfficiency.objects.filter(
            instructor_id=instructor_id,
            date__lte=today
        ).order_by('-date')
        
        if tenant:
            efficiency_query = efficiency_query.filter(tenant=tenant)
        
        efficiency_data = efficiency_query.first()
        
        if efficiency_data:
            return {
                "optimal_study_times": efficiency_data.optimal_study_times or [],
                "content_effectiveness": efficiency_data.content_effectiveness or [],
                "difficulty_progression": efficiency_data.difficulty_progression or {
                    "current_balance": 0,
                    "recommendation": "unavailable"
                },
                "learning_patterns": efficiency_data.learning_patterns or {
                    "peak_learning_days": [],
                    "preferred_session_length": 0,
                    "retention_rate": 0
                }
            }
        
        # If no stored data, calculate from events
        instructor_courses = Course.objects.filter(instructor_id=instructor_id)
        if tenant:
            instructor_courses = instructor_courses.filter(tenant=tenant)
        course_ids = list(instructor_courses.values_list('id', flat=True))
        
        # Get study sessions to calculate optimal times
        last_30_days = today - timedelta(days=30)
        study_sessions = StudySession.objects.filter(
            course_id__in=course_ids,
            started_at__date__gte=last_30_days
        )
        if tenant:
            study_sessions = study_sessions.filter(tenant=tenant)
        
        # Calculate hourly efficiency based on session engagement scores
        hourly_engagement = study_sessions.values('started_at__hour').annotate(
            avg_engagement=Avg('engagement_score')
        ).order_by('-avg_engagement')[:5]
        
        optimal_study_times = [
            {"hour": item['started_at__hour'], "efficiency": float(item['avg_engagement'] or 0)}
            for item in hourly_engagement
        ]
        
        # Calculate content effectiveness from events
        content_events = Event.objects.filter(
            context_data__course_id__in=course_ids,
            created_at__date__gte=last_30_days,
            event_type__in=['VIDEO_COMPLETE', 'ASSESSMENT_PASS', 'CONTENT_COMPLETE']
        )
        if tenant:
            content_events = content_events.filter(tenant=tenant)
        
        video_completions = content_events.filter(event_type='VIDEO_COMPLETE').count()
        assessment_passes = content_events.filter(event_type='ASSESSMENT_PASS').count()
        content_completions = content_events.filter(event_type='CONTENT_COMPLETE').count()
        total_completions = video_completions + assessment_passes + content_completions
        
        content_effectiveness = []
        if total_completions > 0:
            content_effectiveness = [
                {"content_type": "video", "effectiveness": round((video_completions / total_completions) * 100, 2)},
                {"content_type": "quiz", "effectiveness": round((assessment_passes / total_completions) * 100, 2)},
                {"content_type": "text", "effectiveness": round((content_completions / total_completions) * 100, 2)}
            ]
        
        # Calculate peak learning days
        daily_sessions = study_sessions.values('started_at__week_day').annotate(
            session_count=Count('id')
        ).order_by('-session_count')[:3]
        
        day_names = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
        peak_days = [day_names[item['started_at__week_day'] - 1] for item in daily_sessions]
        
        # Calculate average session length
        avg_session_duration = study_sessions.filter(
            duration__isnull=False
        ).aggregate(avg_duration=Avg('duration'))['avg_duration']
        
        preferred_session_length = 0
        if avg_session_duration:
            preferred_session_length = int(avg_session_duration.total_seconds() / 60)
        
        return {
            "optimal_study_times": optimal_study_times,
            "content_effectiveness": content_effectiveness,
            "difficulty_progression": {
                "current_balance": 0,
                "recommendation": "insufficient_data"
            },
            "learning_patterns": {
                "peak_learning_days": peak_days,
                "preferred_session_length": preferred_session_length,
                "retention_rate": 0
            }
        }

    @staticmethod
    def _get_social_learning_metrics(instructor_id: uuid.UUID, tenant: Optional[Tenant]) -> Dict[str, Any]:
        """Get social learning metrics for an instructor."""
        today = timezone.now().date()
        last_30_days = today - timedelta(days=30)
        
        instructor_courses = Course.objects.filter(instructor_id=instructor_id)
        if tenant:
            instructor_courses = instructor_courses.filter(tenant=tenant)
        course_ids = list(instructor_courses.values_list('id', flat=True))
        
        # First check for aggregated SocialLearningMetrics data
        social_metrics = SocialLearningMetrics.objects.filter(
            instructor_id=instructor_id,
            date__gte=last_30_days
        )
        if tenant:
            social_metrics = social_metrics.filter(tenant=tenant)
        
        # If aggregated data exists, sum it up
        if social_metrics.exists():
            aggregated = social_metrics.aggregate(
                total_messages=Sum('discussion_messages'),
                total_participants=Sum('discussion_participants'),
                total_threads=Sum('discussion_threads'),
                total_reviews_submitted=Sum('peer_reviews_submitted'),
                total_reviews_received=Sum('peer_reviews_received'),
                avg_rating=Avg('avg_peer_review_rating'),
                total_projects=Sum('collaborative_projects'),
                total_study_groups=Sum('study_groups')
            )
            
            # Get active counts
            discussion_activity = {
                "total_messages": aggregated['total_messages'] or 0,
                "active_participants": aggregated['total_participants'] or 0,
                "threads_created": aggregated['total_threads'] or 0,
                "avg_response_time": 0  # Would require timestamp analysis
            }
            
            peer_review_activity = {
                "reviews_submitted": aggregated['total_reviews_submitted'] or 0,
                "reviews_received": aggregated['total_reviews_received'] or 0,
                "avg_rating": float(aggregated['avg_rating'] or 0),
                "participation_rate": 0  # Would need enrollment data
            }
        else:
            # Query raw data from individual models
            # Discussion activity
            discussion_interactions = DiscussionInteraction.objects.filter(
                course_id__in=course_ids,
                created_at__date__gte=last_30_days
            )
            if tenant:
                discussion_interactions = discussion_interactions.filter(tenant=tenant)
            
            total_messages = discussion_interactions.filter(
                interaction_type__in=['post', 'reply']
            ).count()
            
            active_participants = discussion_interactions.values('user_id').distinct().count()
            threads_created = discussion_interactions.filter(
                interaction_type='post'
            ).values('discussion_id').distinct().count()
            
            # Calculate average response time (time between posts in same thread)
            # This is simplified - would need more complex query for accurate calculation
            avg_response_time = 0
            
            discussion_activity = {
                "total_messages": total_messages,
                "active_participants": active_participants,
                "threads_created": threads_created,
                "avg_response_time": avg_response_time
            }
            
            # Peer review activity
            peer_reviews = PeerReview.objects.filter(
                course_id__in=course_ids,
                created_at__date__gte=last_30_days
            )
            if tenant:
                peer_reviews = peer_reviews.filter(tenant=tenant)
            
            reviews_submitted = peer_reviews.filter(status='submitted').count()
            reviews_received = peer_reviews.count()
            avg_rating = peer_reviews.aggregate(avg=Avg('rating'))['avg'] or 0
            
            # Calculate participation rate
            total_enrolled = Enrollment.objects.filter(
                course__in=instructor_courses,
                status=Enrollment.Status.ACTIVE
            ).values('user_id').distinct().count()
            
            reviewers_count = peer_reviews.values('reviewer_id').distinct().count()
            participation_rate = 0
            if total_enrolled > 0:
                participation_rate = round((reviewers_count / total_enrolled) * 100, 2)
            
            peer_review_activity = {
                "reviews_submitted": reviews_submitted,
                "reviews_received": reviews_received,
                "avg_rating": round(float(avg_rating), 2),
                "participation_rate": participation_rate
            }
        
        # Collaborative projects
        projects = CollaborativeProject.objects.filter(course_id__in=course_ids)
        if tenant:
            projects = projects.filter(tenant=tenant)
        
        total_projects = projects.count()
        active_collaborations = projects.filter(status='in_progress').count()
        completed_projects = projects.filter(status='completed').count()
        project_completion_rate = 0
        if total_projects > 0:
            project_completion_rate = round((completed_projects / total_projects) * 100, 2)
        
        # Study groups
        study_groups = StudyGroup.objects.filter(course_id__in=course_ids)
        if tenant:
            study_groups = study_groups.filter(tenant=tenant)
        
        total_groups = study_groups.count()
        active_groups = study_groups.filter(is_active=True).count()
        
        # Calculate average group size
        avg_group_size = 0
        if total_groups > 0:
            total_members = sum(sg.members.count() for sg in study_groups)
            avg_group_size = round(total_members / total_groups, 1)
        
        return {
            "discussion_activity": discussion_activity,
            "peer_review_activity": peer_review_activity,
            "collaborative_projects": {
                "total_projects": total_projects,
                "active_collaborations": active_collaborations,
                "completion_rate": project_completion_rate
            },
            "study_groups": {
                "total_groups": total_groups,
                "active_groups": active_groups,
                "avg_group_size": avg_group_size
            }
        }

    @staticmethod
    def _get_revenue_analytics(instructor_id: uuid.UUID, tenant: Optional[Tenant]) -> Dict[str, Any]:
        """Get revenue analytics for an instructor."""
        today = timezone.now().date()
        last_30_days = today - timedelta(days=30)
        first_of_month = today.replace(day=1)
        
        instructor_courses = Course.objects.filter(instructor_id=instructor_id)
        if tenant:
            instructor_courses = instructor_courses.filter(tenant=tenant)
        course_ids = list(instructor_courses.values_list('id', flat=True))
        
        # Query RevenueAnalytics model for revenue data
        revenue_records = RevenueAnalytics.objects.filter(
            instructor_id=instructor_id,
            period_end__gte=last_30_days
        )
        if tenant:
            revenue_records = revenue_records.filter(tenant=tenant)
        
        # Calculate totals from revenue records
        total_revenue = 0
        monthly_revenue = 0
        avg_revenue_per_student = 0
        growth_rate = 0
        
        if revenue_records.exists():
            aggregated = revenue_records.aggregate(
                total=Sum('total_revenue'),
                monthly=Sum('monthly_revenue'),
                avg_per_student=Avg('revenue_per_student'),
                avg_growth=Avg('growth_rate')
            )
            total_revenue = float(aggregated['total'] or 0)
            monthly_revenue = float(aggregated['monthly'] or 0)
            avg_revenue_per_student = float(aggregated['avg_per_student'] or 0)
            growth_rate = float(aggregated['avg_growth'] or 0)
        else:
            # If no RevenueAnalytics records, query InstructorAnalytics
            instructor_analytics = InstructorAnalytics.objects.filter(
                instructor_id=instructor_id,
                date__gte=last_30_days
            ).order_by('-date')
            if tenant:
                instructor_analytics = instructor_analytics.filter(tenant=tenant)
            
            latest = instructor_analytics.first()
            if latest:
                total_revenue = float(latest.total_revenue)
                monthly_revenue = float(latest.monthly_revenue)
                avg_revenue_per_student = float(latest.avg_revenue_per_student)
                growth_rate = float(latest.revenue_growth_rate)
        
        # Get top earning courses
        course_revenue = RevenueAnalytics.objects.filter(
            course_id__in=course_ids,
            period_end__gte=last_30_days
        )
        if tenant:
            course_revenue = course_revenue.filter(tenant=tenant)
        
        top_courses = course_revenue.values('course_id').annotate(
            revenue=Sum('total_revenue')
        ).order_by('-revenue')[:5]
        
        top_earning_courses = []
        for item in top_courses:
            course = Course.objects.filter(id=item['course_id']).first()
            if course:
                top_earning_courses.append({
                    "course_id": str(item['course_id']),
                    "title": course.title,
                    "revenue": float(item['revenue'] or 0)
                })
        
        # If no course-level revenue data, still show courses with zero revenue
        if not top_earning_courses:
            for course in instructor_courses[:5]:
                top_earning_courses.append({
                    "course_id": str(course.id),
                    "title": course.title,
                    "revenue": 0
                })
        
        return {
            "total_revenue": round(total_revenue, 2),
            "monthly_revenue": round(monthly_revenue, 2),
            "average_revenue_per_student": round(avg_revenue_per_student, 2),
            "revenue_growth_rate": round(growth_rate, 2),
            "top_earning_courses": top_earning_courses,
            "payment_methods": {
                # Payment method breakdown would come from payment/billing system
                # Return empty structure if not available
                "credit_card": 0,
                "paypal": 0,
                "bank_transfer": 0
            }
        }

    @staticmethod
    def _get_engagement_trends(instructor_id: uuid.UUID, tenant: Optional[Tenant]) -> Dict[str, Any]:
        """Get engagement trends for an instructor."""
        # Get engagement data over the last 30 days
        today = timezone.now().date()
        thirty_days_ago = today - timedelta(days=30)
        
        instructor_courses = Course.objects.filter(instructor_id=instructor_id)
        if tenant:
            instructor_courses = instructor_courses.filter(tenant=tenant)
        course_ids = list(instructor_courses.values_list('id', flat=True))
        
        # Get events for the last 30 days
        events = Event.objects.filter(
            created_at__date__gte=thirty_days_ago,
            context_data__course_id__in=course_ids
        )
        if tenant:
            events = events.filter(tenant=tenant)
        
        # Calculate daily engagement
        daily_events = events.values('created_at__date').annotate(
            event_count=Count('id'),
            unique_users=Count('user_id', distinct=True)
        ).order_by('created_at__date')
        
        # Get total enrolled for engagement rate calculation
        total_enrolled = Enrollment.objects.filter(
            course__in=instructor_courses,
            status=Enrollment.Status.ACTIVE
        ).values('user_id').distinct().count()
        
        daily_engagement = []
        for item in daily_events:
            engagement_rate = 0
            if total_enrolled > 0:
                engagement_rate = round((item['unique_users'] / total_enrolled) * 100, 2)
            daily_engagement.append({
                "date": item['created_at__date'].isoformat(),
                "engagement_rate": engagement_rate
            })
        
        # Calculate weekly patterns (by day of week)
        weekly_events = events.values('created_at__week_day').annotate(
            unique_users=Count('user_id', distinct=True)
        ).order_by('created_at__week_day')
        
        day_names = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday']
        weekly_patterns = {day: 0 for day in day_names}
        
        for item in weekly_events:
            day_index = item['created_at__week_day'] - 1  # Django weekday is 1-7
            if 0 <= day_index < 7:
                engagement_rate = 0
                if total_enrolled > 0:
                    engagement_rate = round((item['unique_users'] / total_enrolled) * 100, 2)
                weekly_patterns[day_names[day_index]] = engagement_rate
        
        # Calculate hourly patterns
        hourly_events = events.values('created_at__hour').annotate(
            activity=Count('id')
        ).order_by('created_at__hour')
        
        hourly_patterns = [
            {"hour": item['created_at__hour'], "activity": item['activity']}
            for item in hourly_events
        ]
        
        # Calculate device usage from events
        device_events = events.exclude(device_type__isnull=True).exclude(device_type='').values(
            'device_type'
        ).annotate(count=Count('id'))
        
        total_device_events = sum(item['count'] for item in device_events)
        device_usage = {"desktop": 0, "mobile": 0, "tablet": 0}
        
        if total_device_events > 0:
            for item in device_events:
                device = item['device_type'].lower() if item['device_type'] else 'desktop'
                if device in device_usage:
                    device_usage[device] = round((item['count'] / total_device_events) * 100, 2)
        
        # Calculate geographic distribution from events
        geo_events = events.exclude(country__isnull=True).exclude(country='').values(
            'country'
        ).annotate(count=Count('id')).order_by('-count')
        
        total_geo_events = sum(item['count'] for item in geo_events)
        geographic_distribution = {}
        
        if total_geo_events > 0:
            # Group countries into regions
            na_countries = ['United States', 'US', 'USA', 'Canada', 'Mexico']
            europe_countries = ['United Kingdom', 'UK', 'Germany', 'France', 'Spain', 'Italy', 'Netherlands', 'Poland']
            asia_countries = ['China', 'Japan', 'India', 'South Korea', 'Singapore', 'Indonesia', 'Vietnam', 'Thailand']
            
            na_count = europe_count = asia_count = other_count = 0
            
            for item in geo_events:
                country = item['country']
                count = item['count']
                if country in na_countries:
                    na_count += count
                elif country in europe_countries:
                    europe_count += count
                elif country in asia_countries:
                    asia_count += count
                else:
                    other_count += count
            
            geographic_distribution = {
                "north_america": round((na_count / total_geo_events) * 100, 2),
                "europe": round((europe_count / total_geo_events) * 100, 2),
                "asia": round((asia_count / total_geo_events) * 100, 2),
                "other": round((other_count / total_geo_events) * 100, 2)
            }
        
        return {
            "daily_engagement": daily_engagement,
            "weekly_patterns": weekly_patterns,
            "hourly_patterns": hourly_patterns,
            "device_usage": device_usage,
            "geographic_distribution": geographic_distribution
        }

    @staticmethod
    def update_analytics_data(instructor_id: uuid.UUID, tenant: Optional[Tenant] = None):
        """
        Update/refresh analytics data for an instructor.
        This would typically be called by a background task.
        """
        today = timezone.now().date()
        
        # Update course analytics
        ComprehensiveAnalyticsService._update_course_analytics(instructor_id, tenant, today)
        
        # Update instructor analytics
        ComprehensiveAnalyticsService._update_instructor_analytics(instructor_id, tenant, today)
        
        # Update student engagement metrics
        ComprehensiveAnalyticsService._update_student_engagement_metrics(instructor_id, tenant, today)
        
        logger.info(f"Analytics data updated for instructor {instructor_id}")

    @staticmethod
    def _update_course_analytics(instructor_id: uuid.UUID, tenant: Optional[Tenant], date):
        """Update course analytics for a specific date."""
        courses = Course.objects.filter(instructor_id=instructor_id)
        if tenant:
            courses = courses.filter(tenant=tenant)
        
        for course in courses:
            # Get or create course analytics record
            analytics, created = CourseAnalytics.objects.get_or_create(
                tenant=tenant,
                course_id=course.id,
                instructor_id=instructor_id,
                date=date,
                defaults={
                    'total_enrollments': 0,
                    'active_enrollments': 0,
                    'completed_enrollments': 0,
                }
            )
            
            # Update enrollment statistics
            enrollments = Enrollment.objects.filter(course=course)
            analytics.total_enrollments = enrollments.count()
            analytics.active_enrollments = enrollments.filter(
                status=Enrollment.Status.ACTIVE
            ).count()
            analytics.completed_enrollments = enrollments.filter(
                status=Enrollment.Status.COMPLETED
            ).count()
            
            # Calculate completion rate
            if analytics.total_enrollments > 0:
                analytics.avg_completion_rate = (
                    analytics.completed_enrollments / analytics.total_enrollments * 100
                )
            
            analytics.save()

    @staticmethod
    def _update_instructor_analytics(instructor_id: uuid.UUID, tenant: Optional[Tenant], date):
        """Update instructor analytics for a specific date."""
        # Get or create instructor analytics record
        analytics, created = InstructorAnalytics.objects.get_or_create(
            tenant=tenant,
            instructor_id=instructor_id,
            date=date,
            defaults={
                'total_courses': 0,
                'published_courses': 0,
                'total_students': 0,
            }
        )
        
        # Update course statistics
        courses = Course.objects.filter(instructor_id=instructor_id)
        if tenant:
            courses = courses.filter(tenant=tenant)
            
        analytics.total_courses = courses.count()
        analytics.published_courses = courses.filter(is_published=True).count()
        analytics.draft_courses = analytics.total_courses - analytics.published_courses
        
        # Update student statistics
        students = User.objects.filter(
            enrollments__course__instructor_id=instructor_id
        ).distinct()
        if tenant:
            students = students.filter(enrollments__course__tenant=tenant)
            
        analytics.total_students = students.count()
        
        # Calculate active students (activity in last 7 days)
        week_ago = timezone.now() - timedelta(days=7)
        active_students = Event.objects.filter(
            user__in=students,
            created_at__gte=week_ago
        ).values('user_id').distinct().count()
        
        analytics.active_students = active_students
        
        analytics.save()

    @staticmethod
    def _update_student_engagement_metrics(instructor_id: uuid.UUID, tenant: Optional[Tenant], date):
        """Update student engagement metrics for all students in instructor's courses."""
        # Get all students enrolled in instructor's courses
        students = User.objects.filter(
            enrollments__course__instructor_id=instructor_id
        ).distinct()
        
        if tenant:
            students = students.filter(enrollments__course__tenant=tenant)
        
        for student in students:
            # Get student's courses with this instructor
            courses = Course.objects.filter(
                instructor_id=instructor_id,
                enrollments__user=student
            )
            
            for course in courses:
                # Get or create engagement metric record
                engagement, created = StudentEngagementMetric.objects.get_or_create(
                    tenant=tenant,
                    user=student,
                    course_id=course.id,
                    date=date,
                    defaults={
                        'daily_active_time': 0,
                        'content_views': 0,
                        'video_watches': 0,
                    }
                )
                
                # Update engagement metrics from events
                day_start = timezone.make_aware(datetime.combine(date, datetime.min.time()))
                day_end = day_start + timedelta(days=1)
                
                daily_events = Event.objects.filter(
                    user=student,
                    created_at__gte=day_start,
                    created_at__lt=day_end,
                    context_data__course_id=str(course.id)
                )
                
                engagement.content_views = daily_events.filter(
                    event_type='CONTENT_VIEW'
                ).count()
                engagement.video_watches = daily_events.filter(
                    event_type='VIDEO_WATCH'
                ).count()
                engagement.quiz_attempts = daily_events.filter(
                    event_type='QUIZ_ATTEMPT'
                ).count()
                
                # Calculate risk score (simple heuristic)
                engagement.risk_score = ComprehensiveAnalyticsService._calculate_risk_score(
                    student, course, date
                )
                
                engagement.save()

    @staticmethod
    def _calculate_risk_score(student: User, course: Course, date) -> float:
        """Calculate a simple risk score for a student."""
        # Simple heuristic based on recent activity
        week_ago = timezone.now() - timedelta(days=7)
        
        recent_activity = Event.objects.filter(
            user=student,
            created_at__gte=week_ago,
            context_data__course_id=str(course.id)
        ).count()
        
        # Risk factors
        risk_score = 0
        
        if recent_activity == 0:
            risk_score += 40  # No recent activity
        elif recent_activity < 5:
            risk_score += 20  # Low activity
        
        # Check assessment performance
        recent_assessments = AssessmentAttempt.objects.filter(
            user=student,
            assessment__course=course,
            created_at__gte=week_ago
        )
        
        if recent_assessments.exists():
            avg_score = recent_assessments.aggregate(avg=Avg('score'))['avg']
            if avg_score and avg_score < 60:
                risk_score += 30  # Poor performance
        
        return min(risk_score, 100)  # Cap at 100

# --- Async Task Definitions (if logging events asynchronously) ---
# from celery import shared_task
# @shared_task(name="analytics.log_event")
# def log_event_task(event_data_dict):
#     """ Async task to log an event. """
#     # Reconstruct user/tenant objects or pass IDs? Pass IDs for reliability.
#     user_id = event_data_dict.pop('user_id', None)
#     tenant_id = event_data_dict.pop('tenant_id', None)
#     event_data_dict['user'] = User.objects.filter(id=user_id).first() if user_id else None
#     event_data_dict['tenant'] = Tenant.objects.filter(id=tenant_id).first() if tenant_id else None
#     try:
#         Event.objects.create(**event_data_dict)
#     except Exception as e:
#          logger.error(f"Failed to log event async: {event_data_dict.get('event_type')}. Error: {e}", exc_info=True)
