import logging
from django.conf import settings
from django.http import JsonResponse # Can be used for simple views
from django.utils import timezone
from datetime import timedelta, date
from django.db.models import Count, Q, Avg, Sum
from django.db.models.functions import TruncMonth

from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated # Django REST Framework's built-in

from apps.core.models import Tenant # Assuming Tenant is in core.models
from apps.users.models import User
from apps.courses.models import Course, ContentItem
from apps.analytics.models import Event, Report, RevenueAnalytics # Assuming Event and Report are in analytics.models
from apps.analytics.serializers import ReportSerializer, InstructorReportSerializer
from apps.enrollments.models import Enrollment, LearnerProgress
from apps.assessments.models import Assessment, AssessmentAttempt
from .models import Tenant, TenantDomain
from .serializers import TenantSerializer, TenantDomainSerializer
from apps.users.permissions import IsAdminOrTenantAdmin, IsLearner, IsInstructorOrAdmin, IsAdmin, is_admin_user
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

logger = logging.getLogger(__name__)

# --- Existing or Placeholder Core Views (if any) ---
# Example health check:
def health_check_view(request):
    return JsonResponse({"status": "ok", "timestamp": timezone.now().isoformat()})


# --- Admin Dashboard Statistics View ---
class AdminDashboardStatsView(APIView):
    """
    Provides aggregated statistics for the admin dashboard.
    Requires admin user privileges.
    
    - Superusers see platform-wide stats across all tenants
    - Tenant admins see stats scoped to their own tenant only
    """
    permission_classes = [IsAdmin] # Uses RBAC - allows role=ADMIN, is_staff, or is_superuser

    def _get_tenant_filter(self, user):
        """
        Returns the tenant to filter by, or None for superusers (platform-wide access).
        """
        if user.is_superuser:
            return None  # Superusers see all data
        # Tenant admins only see their own tenant's data
        return getattr(user, 'tenant', None)

    def get(self, request, format=None):
        try:
            user = request.user
            tenant = self._get_tenant_filter(user)
            is_platform_admin = tenant is None  # True for superusers
            
            # Base querysets with tenant filtering
            if tenant:
                users_qs = User.objects.filter(tenant=tenant)
                courses_qs = Course.objects.filter(tenant=tenant)
                enrollments_qs = Enrollment.objects.filter(course__tenant=tenant)
                events_qs = Event.objects.filter(tenant=tenant)
                tenants_qs = Tenant.objects.filter(id=tenant.id)
            else:
                users_qs = User.objects.all()
                courses_qs = Course.objects.all()
                enrollments_qs = Enrollment.objects.all()
                events_qs = Event.objects.all()
                tenants_qs = Tenant.objects.all()
            
            total_tenants = tenants_qs.count() if is_platform_admin else 1
            total_users = users_qs.filter(is_active=True).count()
            total_courses = courses_qs.count()

            # Active users today
            today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
            active_users_today = users_qs.filter(last_login__gte=today_start).count()

            # User growth (last 6 months)
            six_months_ago = timezone.now() - timedelta(days=6*30)
            user_growth_data = users_qs.filter(date_joined__gte=six_months_ago)\
                .annotate(month=TruncMonth('date_joined'))\
                .values('month')\
                .annotate(users=Count('id'))\
                .order_by('month')

            user_growth_formatted = [
                {"month": item['month'].strftime("%b %Y"), "users": item['users']}
                for item in user_growth_data
            ]

            # Recent System Events (scoped by tenant)
            if is_platform_admin:
                recent_system_events_qs = Event.objects.filter(
                    Q(event_type='TENANT_CREATED') |
                    Q(event_type='ADMIN_LOGIN_SUCCESS', user__is_superuser=True) |
                    Q(event_type='SYSTEM_ERROR_CRITICAL')
                ).select_related('user').order_by('-created_at')[:5]
            else:
                # Tenant admins see events within their tenant
                recent_system_events_qs = events_qs.filter(
                    Q(event_type='ADMIN_LOGIN_SUCCESS') |
                    Q(event_type='USER_LOGIN') |
                    Q(event_type='COURSE_CREATED') |
                    Q(event_type='ENROLLMENT_CREATED')
                ).select_related('user').order_by('-created_at')[:5]

            def build_event_description(event):
                """Build a meaningful description for an event based on its type and context."""
                context = event.context_data or {}
                user_email = event.user.email if event.user else "System"
                
                # Check for explicit summary first
                if context.get('summary'):
                    return context['summary']
                
                # Build description based on event type
                event_type = event.event_type
                
                if event_type in ('USER_LOGIN', 'ADMIN_LOGIN_SUCCESS'):
                    return f"{user_email} logged in"
                elif event_type == 'USER_LOGOUT':
                    return f"{user_email} logged out"
                elif event_type == 'USER_REGISTER':
                    return f"{user_email} registered"
                elif event_type == 'COURSE_CREATED':
                    course_title = context.get('course_title', 'a course')
                    return f"{user_email} created \"{course_title}\""
                elif event_type == 'COURSE_VIEW':
                    course_title = context.get('course_title', 'a course')
                    return f"{user_email} viewed \"{course_title}\""
                elif event_type in ('COURSE_ENROLL', 'ENROLLMENT_CREATED'):
                    course_title = context.get('course_title', 'a course')
                    return f"{user_email} enrolled in \"{course_title}\""
                elif event_type == 'COURSE_COMPLETE':
                    course_title = context.get('course_title', 'a course')
                    return f"{user_email} completed \"{course_title}\""
                elif event_type == 'ASSESSMENT_SUBMIT':
                    score = context.get('score')
                    if score is not None:
                        return f"{user_email} submitted assessment (Score: {score}%)"
                    return f"{user_email} submitted an assessment"
                elif event_type == 'CONTENT_COMPLETE':
                    content_title = context.get('content_title', 'content')
                    return f"{user_email} completed \"{content_title}\""
                elif event_type == 'TENANT_CREATED':
                    tenant_name = context.get('tenant_name', 'a tenant')
                    return f"Tenant \"{tenant_name}\" was created"
                elif event_type == 'SYSTEM_ERROR_CRITICAL':
                    error_msg = context.get('error', 'Unknown error')
                    return f"Critical error: {error_msg[:50]}"
                else:
                    # Fallback: use user email as context
                    return f"By {user_email}"

            recent_events_formatted = [
                {
                    "id": str(event.id),
                    "type": event.event_type,
                    "description": build_event_description(event),
                    "user_email": event.user.email if event.user else "System",
                    "timestamp": event.created_at.isoformat()
                } for event in recent_system_events_qs
            ]

            # ============================================================
            # PROACTIVE DASHBOARD METRICS - Platform Health & Alerts
            # ============================================================
            
            two_weeks_ago = timezone.now() - timedelta(days=14)
            thirty_days_ago = timezone.now() - timedelta(days=30)
            
            # Tenants needing attention (only for superusers)
            tenants_needing_attention = []
            if is_platform_admin:
                try:
                    for t in Tenant.objects.filter(is_active=True):
                        issues = []
                        severity = "low"
                        
                        tenant_users = User.objects.filter(tenant=t, is_active=True).count()
                        tenant_courses = Course.objects.filter(tenant=t).count()
                        tenant_enrollments = Enrollment.objects.filter(course__tenant=t).count()
                        
                        active_users_14d = User.objects.filter(
                            tenant=t,
                            is_active=True,
                            last_login__gte=two_weeks_ago
                        ).count()
                        
                        if tenant_courses == 0 and tenant_users > 0:
                            issues.append({
                                "type": "no_courses",
                                "message": "No courses created yet",
                                "suggestion": "Reach out to help them get started with course creation"
                            })
                            severity = "medium"
                        
                        if tenant_users >= 5:
                            active_rate = (active_users_14d / tenant_users) * 100 if tenant_users > 0 else 0
                            if active_rate < 20:
                                issues.append({
                                    "type": "low_engagement",
                                    "message": f"Only {round(active_rate)}% of users active in last 14 days",
                                    "suggestion": "Consider sending engagement campaigns or checking in with tenant admin"
                                })
                                if severity == "low":
                                    severity = "medium"
                        
                        if tenant_courses > 0 and tenant_enrollments == 0:
                            issues.append({
                                "type": "no_enrollments",
                                "message": f"{tenant_courses} course(s) but no enrollments",
                                "suggestion": "Help tenant promote courses to their learners"
                            })
                            if severity == "low":
                                severity = "medium"
                        
                        if t.created_at < thirty_days_ago:
                            recent_activity = Event.objects.filter(
                                tenant=t,
                                created_at__gte=thirty_days_ago
                            ).exists()
                            
                            if not recent_activity and tenant_users > 0:
                                issues.append({
                                    "type": "inactive_tenant",
                                    "message": "No activity in the last 30 days",
                                    "suggestion": "Schedule a check-in call with tenant admin"
                                })
                                severity = "high"
                        
                        if issues:
                            tenants_needing_attention.append({
                                "tenantId": str(t.id),
                                "tenantName": t.name,
                                "tenantSlug": t.slug,
                                "totalUsers": tenant_users,
                                "totalCourses": tenant_courses,
                                "totalEnrollments": tenant_enrollments,
                                "issues": issues,
                                "severity": severity
                            })
                    
                    severity_order = {"high": 0, "medium": 1, "low": 2}
                    tenants_needing_attention.sort(key=lambda x: severity_order.get(x['severity'], 3))
                    tenants_needing_attention = tenants_needing_attention[:10]
                except Exception as e:
                    logger.warning(f"Error calculating tenants needing attention: {e}")
            
            # Platform/Tenant alerts
            platform_alerts = []
            try:
                # Alert 1: Pending user approvals (scoped by tenant)
                pending_users = users_qs.filter(
                    status='INVITED',
                    is_active=False
                ).count()
                
                if pending_users > 0:
                    platform_alerts.append({
                        "type": "pending_approvals",
                        "severity": "medium" if pending_users < 10 else "high",
                        "title": f"{pending_users} user(s) pending approval",
                        "message": "New users are waiting for account activation",
                        "actionUrl": "/admin/users?status=invited",
                        "actionLabel": "Review Users"
                    })
                
                # Alert 2: Overdue grading (scoped by tenant)
                three_days_ago = timezone.now() - timedelta(days=3)
                overdue_grading_qs = AssessmentAttempt.objects.filter(
                    status=AssessmentAttempt.AttemptStatus.SUBMITTED,
                    end_time__lt=three_days_ago
                )
                if tenant:
                    overdue_grading_qs = overdue_grading_qs.filter(assessment__course__tenant=tenant)
                overdue_grading_count = overdue_grading_qs.count()
                
                if overdue_grading_count > 0:
                    platform_alerts.append({
                        "type": "overdue_grading",
                        "severity": "high" if overdue_grading_count > 20 else "medium",
                        "title": f"{overdue_grading_count} assessment(s) awaiting grading",
                        "message": "Some submissions have been waiting for more than 3 days",
                        "actionUrl": "/admin/analytics",
                        "actionLabel": "View Analytics"
                    })
                
                # Alert 3: Inactive tenants (only for superusers)
                if is_platform_admin:
                    inactive_tenant_count = 0
                    for t in Tenant.objects.filter(is_active=True):
                        has_recent_login = User.objects.filter(
                            tenant=t,
                            last_login__gte=thirty_days_ago
                        ).exists()
                        if not has_recent_login:
                            inactive_tenant_count += 1
                    
                    if inactive_tenant_count > 0:
                        platform_alerts.append({
                            "type": "inactive_tenants",
                            "severity": "low" if inactive_tenant_count < 3 else "medium",
                            "title": f"{inactive_tenant_count} tenant(s) with no recent activity",
                            "message": "These tenants haven't had any user logins in 30 days",
                            "actionUrl": "/admin/tenants",
                            "actionLabel": "View Tenants"
                        })
                
                # Alert 4: System errors (scoped by tenant)
                twenty_four_hours_ago = timezone.now() - timedelta(hours=24)
                system_errors_qs = events_qs.filter(
                    event_type='SYSTEM_ERROR_CRITICAL',
                    created_at__gte=twenty_four_hours_ago
                )
                system_errors = system_errors_qs.count()
                
                if system_errors > 0:
                    platform_alerts.append({
                        "type": "system_errors",
                        "severity": "high",
                        "title": f"{system_errors} critical system error(s) in last 24 hours",
                        "message": "Review system logs for details",
                        "actionUrl": "/admin/analytics?tab=event-log",
                        "actionLabel": "View Event Log"
                    })
                
                alert_severity_order = {"high": 0, "medium": 1, "low": 2}
                platform_alerts.sort(key=lambda x: alert_severity_order.get(x['severity'], 3))
            except Exception as e:
                logger.warning(f"Error calculating platform alerts: {e}")
            
            # Quick stats (scoped by tenant)
            quick_stats = {}
            try:
                one_week_ago = timezone.now() - timedelta(days=7)
                quick_stats["newUsersThisWeek"] = users_qs.filter(
                    date_joined__gte=one_week_ago
                ).count()
                
                quick_stats["newEnrollmentsThisWeek"] = enrollments_qs.filter(
                    enrolled_at__gte=one_week_ago
                ).count()
                
                quick_stats["coursesPublishedThisWeek"] = courses_qs.filter(
                    status=Course.Status.PUBLISHED,
                    updated_at__gte=one_week_ago
                ).count()
                
                if is_platform_admin:
                    active_tenant_ids = User.objects.filter(
                        last_login__gte=one_week_ago,
                        tenant__isnull=False
                    ).values_list('tenant_id', flat=True).distinct()
                    quick_stats["activeTenantsThisWeek"] = len(set(active_tenant_ids))
                else:
                    # For tenant admins, show active users in their tenant instead
                    quick_stats["activeUsersThisWeek"] = users_qs.filter(
                        last_login__gte=one_week_ago
                    ).count()
                
                quick_stats["coursesCompletedThisWeek"] = enrollments_qs.filter(
                    status=Enrollment.Status.COMPLETED,
                    completed_at__gte=one_week_ago
                ).count()
            except Exception as e:
                logger.warning(f"Error calculating quick stats: {e}")
                quick_stats = {
                    "newUsersThisWeek": 0,
                    "newEnrollmentsThisWeek": 0,
                    "coursesPublishedThisWeek": 0,
                    "coursesCompletedThisWeek": 0
                }
                if is_platform_admin:
                    quick_stats["activeTenantsThisWeek"] = 0
                else:
                    quick_stats["activeUsersThisWeek"] = 0

            stats = {
                "totalTenants": total_tenants,
                "totalUsers": total_users,
                "totalCourses": total_courses,
                "activeUsersToday": active_users_today,
                "userGrowth": user_growth_formatted,
                "recentSystemEvents": recent_events_formatted,
                "platformAlerts": platform_alerts,
                "quickStats": quick_stats,
                # Include tenant context info for frontend
                "isPlatformAdmin": is_platform_admin,
            }
            
            # Only include tenant-level metrics for superusers
            if is_platform_admin:
                stats["tenantsNeedingAttention"] = tenants_needing_attention
            
            return Response(stats)

        except Exception as e:
            logger.error(f"Error generating admin dashboard stats: {e}", exc_info=True)
            return Response({"detail": "Could not retrieve dashboard statistics."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class LearnerRecommendationsView(APIView):
    """
    Provides AI-powered content recommendations for learners.
    Uses the PersonalizationService to recommend courses and learning paths.
    """
    permission_classes = [IsAuthenticated, IsLearner]

    def get(self, request, format=None):
        user = request.user
        
        try:
            from apps.ai_engine.services import PersonalizationService
            
            # Get query parameters
            limit = int(request.query_params.get('limit', 10))
            exclude_enrolled = request.query_params.get('exclude_enrolled', 'true').lower() == 'true'
            
            # Build context for recommendations
            context = {
                'limit': min(limit, 20),  # Cap at 20 recommendations
                'exclude_enrolled': exclude_enrolled,
            }
            
            # Get recommendations from PersonalizationService
            recommendations = PersonalizationService.recommend_content(user, context)
            
            return Response({
                'recommendations': recommendations,
                'total': len(recommendations),
            })
            
        except Exception as e:
            logger.error(f"Error fetching recommendations for user {user.id}: {e}", exc_info=True)
            return Response(
                {"detail": "Could not retrieve recommendations."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class LearnerDashboardStatsView(APIView):
    """
    Provides statistics for the learner dashboard.
    """
    permission_classes = [IsAuthenticated, IsLearner]

    def get(self, request, format=None):
        user = request.user
        
        try:
            # Enrollments
            enrollments = Enrollment.objects.filter(user=user).select_related('course')
            
            active_courses = enrollments.filter(status=Enrollment.Status.ACTIVE).count()
            completed_courses = enrollments.filter(status=Enrollment.Status.COMPLETED).count()
            
            # Certificates earned
            certificates_earned = 0
            try:
                from apps.enrollments.models import Certificate
                certificates_earned = Certificate.objects.filter(user=user, status=Certificate.Status.ISSUED).count()
            except ImportError:
                pass
            
            # Learning streak - consecutive days with learning activity
            learning_streak = self.calculate_learning_streak(user)
            
            # Overall Progress - Include both active and completed enrollments
            aggregation = enrollments.filter(status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED]).aggregate(avg_progress=Avg('progress'))
            overall_progress = aggregation['avg_progress'] or 0

            # Total study hours - Based on completed content items (estimate)
            completed_content_count = LearnerProgress.objects.filter(enrollment__user=user, status=LearnerProgress.Status.COMPLETED).count()
            total_study_hours = round(completed_content_count * 0.25, 1)  # Assume 15 minutes per item
            
            # Lessons completed (individual content items)
            lessons_completed = completed_content_count
            
            # Average assessment score
            average_assessment_score = self.calculate_average_assessment_score(user)

            # Learning paths progress
            learning_paths = self.get_learning_paths_progress(user)
            
            # Weekly goals tracking
            weekly_stats = self.get_weekly_stats(user)

            # Recent Activity
            recent_activity_qs = LearnerProgress.objects.filter(
                enrollment__user=user
            ).select_related('content_item', 'enrollment__course').order_by('-updated_at')[:5]
            
            recent_activity = []
            for item in recent_activity_qs:
                activity_type = "Completed" if item.status == LearnerProgress.Status.COMPLETED else "Started"
                recent_activity.append({
                    "description": f"{activity_type} '{item.content_item.title}' in '{item.enrollment.course.title}'",
                    "timestamp": item.updated_at.strftime("%b %d, %Y at %I:%M %p")
                })

            # Upcoming Deadlines
            # Use start of today (timezone-aware) for DateTimeField comparison
            today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
            upcoming_deadlines_qs = Assessment.objects.filter(
                course__enrollments__user=user,
                course__enrollments__status__in=[Enrollment.Status.ACTIVE],
                due_date__gte=today_start,
                is_published=True
            ).select_related('course').order_by('due_date')[:3]
            
            upcoming_deadlines = []
            for assessment in upcoming_deadlines_qs:
                # Check if user has already completed this assessment
                has_passed = AssessmentAttempt.objects.filter(
                    assessment=assessment,
                    user=user,
                    is_passed=True
                ).exists()
                
                if not has_passed:
                    upcoming_deadlines.append({
                        "title": assessment.title,
                        "course": assessment.course.title,
                        "dueDate": assessment.due_date.strftime("%b %d, %Y")
                    })

            # Recent achievements (certificates and milestones)
            recent_achievements = self.get_recent_achievements(user)

            # Continue learning - get most recently accessed active course with next lesson
            continue_learning = self.get_continue_learning(user)
            
            # In-progress courses with progress details
            courses_in_progress = self.get_courses_in_progress(user)

            stats = {
                "activeCourses": active_courses,
                "completedCourses": completed_courses,
                "certificatesEarned": certificates_earned,
                "learningStreak": learning_streak,
                "overallProgress": round(overall_progress),
                "totalStudyHours": total_study_hours,
                "lessonsCompleted": lessons_completed,
                "averageAssessmentScore": round(average_assessment_score),
                "learningPaths": learning_paths,
                "weeklyLessonsCompleted": weekly_stats['lessons'],
                "weeklyAssessmentsTaken": weekly_stats['assessments'],
                "weeklyStudyHours": weekly_stats['study_hours'],
                "recentActivity": recent_activity,
                "upcomingDeadlines": upcoming_deadlines,
                "recentAchievements": recent_achievements,
                "continueLearning": continue_learning,
                "coursesInProgress": courses_in_progress,
            }
            return Response(stats)
        except Exception as e:
            logger.error(f"Error generating learner dashboard stats for user {user.id}: {e}", exc_info=True)
            return Response({"detail": "Could not retrieve dashboard statistics."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def calculate_learning_streak(self, user):
        """Calculate consecutive days of learning activity."""
        try:
            # Get recent learning progress ordered by date
            recent_dates = LearnerProgress.objects.filter(
                enrollment__user=user,
                status=LearnerProgress.Status.COMPLETED
            ).values_list('updated_at__date', flat=True).distinct().order_by('-updated_at__date')[:30]
            
            if not recent_dates:
                return 0
                
            streak = 0
            current_date = timezone.now().date()
            
            # Check if there's activity today or yesterday to start streak
            recent_dates_list = list(recent_dates)
            if recent_dates_list and (recent_dates_list[0] == current_date or recent_dates_list[0] == current_date - timedelta(days=1)):
                streak = 1
                last_date = recent_dates_list[0]
                
                for activity_date in recent_dates_list[1:]:
                    if last_date - activity_date == timedelta(days=1):
                        streak += 1
                        last_date = activity_date
                    else:
                        break
            
            return streak
        except Exception as e:
            logger.error(f"Error calculating learning streak for user {user.id}: {e}")
            return 0

    def calculate_average_assessment_score(self, user):
        """Calculate average assessment score from completed attempts."""
        try:
            attempts = AssessmentAttempt.objects.filter(
                user=user,
                status__in=[AssessmentAttempt.AttemptStatus.SUBMITTED, AssessmentAttempt.AttemptStatus.GRADED],
                score__isnull=False,
                max_score__isnull=False,
                max_score__gt=0
            )
            
            if not attempts.exists():
                return 0
                
            total_percentage = 0
            count = 0
            
            for attempt in attempts:
                percentage = (float(attempt.score) / float(attempt.max_score)) * 100
                total_percentage += percentage
                count += 1
                
            return total_percentage / count if count > 0 else 0
        except Exception as e:
            logger.error(f"Error calculating average assessment score for user {user.id}: {e}")
            return 0

    def get_learning_paths_progress(self, user):
        """Get learning paths progress for the user."""
        try:
            from apps.learning_paths.models import LearningPathProgress, LearningPathStepProgress
            
            path_progress = LearningPathProgress.objects.filter(
                user=user,
                status__in=[LearningPathProgress.Status.IN_PROGRESS, LearningPathProgress.Status.COMPLETED]
            ).select_related('learning_path').prefetch_related('step_progress')[:4]
            
            learning_paths = []
            for progress in path_progress:
                total_steps = progress.learning_path.steps.count()
                completed_steps = progress.step_progress.filter(
                    status=LearningPathStepProgress.Status.COMPLETED
                ).count()
                
                learning_paths.append({
                    "title": progress.learning_path.title,
                    "progressPercentage": round(progress.progress_percentage),
                    "completedSteps": completed_steps,
                    "totalSteps": total_steps
                })
            
            return learning_paths
        except ImportError:
            # Learning paths not available
            return []
        except Exception as e:
            logger.error(f"Error fetching learning paths for user {user.id}: {e}", exc_info=True)
            return []

    def get_weekly_stats(self, user):
        """Get weekly learning statistics."""
        try:
            week_start = timezone.now().date() - timedelta(days=timezone.now().weekday())
            
            # Weekly lessons completed
            weekly_lessons = LearnerProgress.objects.filter(
                enrollment__user=user,
                status=LearnerProgress.Status.COMPLETED,
                updated_at__date__gte=week_start
            ).count()
            
            # Weekly assessments taken
            weekly_assessments = AssessmentAttempt.objects.filter(
                user=user,
                start_time__date__gte=week_start,
                status__in=[AssessmentAttempt.AttemptStatus.SUBMITTED, AssessmentAttempt.AttemptStatus.GRADED]
            ).count()
            
            # Weekly study hours (estimated)
            weekly_study_hours = round(weekly_lessons * 0.25, 1)
            
            return {
                'lessons': weekly_lessons,
                'assessments': weekly_assessments,
                'study_hours': weekly_study_hours
            }
        except Exception as e:
            logger.error(f"Error calculating weekly stats for user {user.id}: {e}")
            return {'lessons': 0, 'assessments': 0, 'study_hours': 0}

    def get_recent_achievements(self, user):
        """Get recent achievements and certificates."""
        try:
            from apps.enrollments.models import Certificate
            
            recent_certs = Certificate.objects.filter(
                user=user,
                status=Certificate.Status.ISSUED
            ).select_related('course').order_by('-issued_at')[:4]
            
            achievements = []
            for cert in recent_certs:
                achievements.append({
                    "title": f"Certificate: {cert.course.title}",
                    "earnedDate": cert.issued_at.strftime("%b %d, %Y")
                })
            
            return achievements
        except ImportError:
            return []
        except Exception as e:
            logger.error(f"Error fetching achievements for user {user.id}: {e}")
            return []

    def get_continue_learning(self, user):
        """Get the most recently accessed active course with next lesson info."""
        try:
            # Get most recently accessed active enrollment
            recent_enrollment = Enrollment.objects.filter(
                user=user,
                status=Enrollment.Status.ACTIVE
            ).select_related('course').order_by('-updated_at').first()
            
            if not recent_enrollment:
                return None
            
            course = recent_enrollment.course
            
            # Get all content items for this course ordered by module and position
            # Used for finding next item to continue (includes all published items)
            all_content_items = ContentItem.objects.filter(
                module__course=course,
                is_published=True
            ).select_related('module').order_by('module__order', 'order')
            
            # Get only required items for progress calculation (consistent with enrollment.progress)
            required_content_items = all_content_items.filter(is_required=True)
            
            # Get completed content item IDs for this enrollment
            completed_item_ids = set(
                LearnerProgress.objects.filter(
                    enrollment=recent_enrollment,
                    status=LearnerProgress.Status.COMPLETED
                ).values_list('content_item_id', flat=True)
            )
            
            # Find the next incomplete item (the one to continue with) - check all items
            next_item = None
            for item in all_content_items:
                if item.id not in completed_item_ids:
                    next_item = item
                    break
            
            # Calculate progress using only required items (consistent with courses page)
            required_item_ids = set(required_content_items.values_list('id', flat=True))
            total_items = len(required_item_ids)
            completed_count = len(completed_item_ids & required_item_ids)
            progress_percentage = round((completed_count / total_items) * 100) if total_items > 0 else 0
            
            return {
                "courseId": course.id,
                "courseTitle": course.title,
                "courseSlug": course.slug,
                "courseThumbnail": course.thumbnail.url if course.thumbnail else None,
                "progressPercentage": progress_percentage,
                "completedLessons": completed_count,
                "totalLessons": total_items,
                "nextLesson": {
                    "id": next_item.id,
                    "title": next_item.title,
                    "moduleTitle": next_item.module.title,
                    "contentType": next_item.content_type,
                } if next_item else None
            }
        except Exception as e:
            logger.error(f"Error getting continue learning for user {user.id}: {e}")
            return None

    def get_courses_in_progress(self, user):
        """Get all in-progress courses with progress details."""
        try:
            # Get active enrollments ordered by most recently updated
            active_enrollments = Enrollment.objects.filter(
                user=user,
                status=Enrollment.Status.ACTIVE
            ).select_related('course').order_by('-updated_at')[:6]
            
            courses = []
            for enrollment in active_enrollments:
                course = enrollment.course
                
                # Get only required, published content items for progress calculation
                # This is consistent with enrollment.progress and courses page
                required_items = ContentItem.objects.filter(
                    module__course=course,
                    is_published=True,
                    is_required=True
                )
                total_items = required_items.count()
                
                # Count completed items that are also required
                completed_items = LearnerProgress.objects.filter(
                    enrollment=enrollment,
                    status=LearnerProgress.Status.COMPLETED,
                    content_item__in=required_items
                ).count()
                
                progress_percentage = round((completed_items / total_items) * 100) if total_items > 0 else 0
                
                courses.append({
                    "courseId": course.id,
                    "courseTitle": course.title,
                    "courseSlug": course.slug,
                    "courseThumbnail": course.thumbnail.url if course.thumbnail else None,
                    "progressPercentage": progress_percentage,
                    "completedLessons": completed_items,
                    "totalLessons": total_items,
                    "lastAccessedAt": enrollment.updated_at.strftime("%b %d, %Y")
                })
            
            return courses
        except Exception as e:
            logger.error(f"Error getting courses in progress for user {user.id}: {e}")
            return []


class InstructorDashboardStatsView(APIView):
    """
    Provides statistics for the instructor dashboard.
    """
    permission_classes = [IsAuthenticated, IsInstructorOrAdmin]

    def get(self, request, format=None):
        user = request.user
        
        try:
            # Courses taught by this instructor
            instructor_courses = Course.objects.filter(instructor=user).select_related('tenant')
            
            total_courses = instructor_courses.count()
            published_courses = instructor_courses.filter(status=Course.Status.PUBLISHED).count()
            draft_courses = instructor_courses.filter(status=Course.Status.DRAFT).count()
            
            # Total enrollments across all instructor's courses
            total_enrollments = Enrollment.objects.filter(course__instructor=user).count()
            active_enrollments = Enrollment.objects.filter(course__instructor=user, status=Enrollment.Status.ACTIVE).count()
            
            # Active students count (distinct users enrolled in instructor's courses)
            active_students = User.objects.filter(
                enrollments__course__instructor=user,
                enrollments__status=Enrollment.Status.ACTIVE
            ).distinct().count()

            # Pending grading count
            pending_grading = 0
            try:
                pending_grading = AssessmentAttempt.objects.filter(
                    assessment__course__instructor=user,
                    status=AssessmentAttempt.AttemptStatus.SUBMITTED
                ).count()
            except Exception:
                pass  # If AssessmentAttempt model has issues

            # Average completion rate across all courses
            avg_completion_rate = 0
            try:
                course_completion_rates = []
                for course in instructor_courses:
                    total_enrollments_course = Enrollment.objects.filter(course=course).count()
                    completed_enrollments = Enrollment.objects.filter(
                        course=course, 
                        status=Enrollment.Status.COMPLETED
                    ).count()
                    if total_enrollments_course > 0:
                        completion_rate = (completed_enrollments / total_enrollments_course) * 100
                        course_completion_rates.append(completion_rate)
                
                avg_completion_rate = round(sum(course_completion_rates) / len(course_completion_rates), 1) if course_completion_rates else 0
            except Exception:
                pass

            # Recent assessments and average scores
            recent_assessments_data = []
            try:
                recent_assessments = Assessment.objects.filter(
                    course__instructor=user
                ).select_related('course').order_by('-created_at')[:5]
                
                recent_assessments_data = [{
                    "title": assessment.title,
                    "course": assessment.course.title,
                    "dueDate": assessment.due_date.strftime("%Y-%m-%d") if assessment.due_date else None,
                    "createdAt": assessment.created_at.isoformat()
                } for assessment in recent_assessments]
            except Exception:
                pass
            
            # Recent student activity across instructor's courses
            recent_activity = []
            try:
                recent_activity_qs = LearnerProgress.objects.filter(
                    enrollment__course__instructor=user
                ).select_related('content_item', 'enrollment__course', 'enrollment__user').order_by('-updated_at')[:10]
                
                recent_activity = [{
                    "description": f"{item.enrollment.user.get_full_name() or item.enrollment.user.email} completed '{item.content_item.title}' in '{item.enrollment.course.title}'",
                    "timestamp": item.updated_at.isoformat()
                } for item in recent_activity_qs]
            except Exception:
                pass
            
            # Upcoming assessment deadlines
            upcoming_deadlines = []
            try:
                # Use start of today (timezone-aware) for DateTimeField comparison
                today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
                upcoming_deadlines_qs = Assessment.objects.filter(
                    course__instructor=user,
                    due_date__gte=today_start
                ).select_related('course').order_by('due_date')[:5]
                
                upcoming_deadlines = [{
                    "title": assessment.title,
                    "course": assessment.course.title,
                    "dueDate": assessment.due_date.strftime("%Y-%m-%d")
                } for assessment in upcoming_deadlines_qs]
            except Exception:
                pass

            # Top courses by enrollment and completion rate
            top_courses = []
            try:
                for course in instructor_courses:
                    enrollments = Enrollment.objects.filter(course=course).count()
                    completed = Enrollment.objects.filter(course=course, status=Enrollment.Status.COMPLETED).count()
                    completion_rate = (completed / enrollments * 100) if enrollments > 0 else 0
                    
                    top_courses.append({
                        "title": course.title,
                        "enrollments": enrollments,
                        "completionRate": round(completion_rate, 1)
                    })
                
                # Sort by completion rate and limit to top 5
                top_courses.sort(key=lambda x: x['completionRate'], reverse=True)
                top_courses = top_courses[:5]
            except Exception:
                pass

            # Top students by activity (based on completed content items in the last week)
            top_students = []
            try:
                one_week_ago = timezone.now() - timedelta(days=7)
                
                # Get students with most completed content items in instructor's courses
                top_students_qs = LearnerProgress.objects.filter(
                    enrollment__course__instructor=user,
                    status=LearnerProgress.Status.COMPLETED,
                    completed_at__gte=one_week_ago
                ).values(
                    'enrollment__user__id',
                    'enrollment__user__first_name',
                    'enrollment__user__last_name',
                    'enrollment__user__email',
                    'enrollment__course__title'
                ).annotate(
                    completed_count=Count('id')
                ).order_by('-completed_count')[:5]
                
                for student in top_students_qs:
                    # Calculate approximate hours spent (estimate: 0.5 hours per completed item)
                    hours_spent = round(student['completed_count'] * 0.5, 1)
                    name = f"{student['enrollment__user__first_name'] or ''} {student['enrollment__user__last_name'] or ''}".strip()
                    if not name:
                        name = student['enrollment__user__email'].split('@')[0]
                    
                    top_students.append({
                        "name": name,
                        "course": student['enrollment__course__title'],
                        "hoursSpent": hours_spent
                    })
            except Exception:
                pass  # If LearnerProgress model has issues, return empty list

            # ============================================================
            # PROACTIVE DASHBOARD METRICS - Course Health & Alerts
            # ============================================================
            
            # Courses needing attention (low enrollment, high attrition, stagnant)
            courses_needing_attention = []
            try:
                two_weeks_ago = timezone.now() - timedelta(days=14)
                thirty_days_ago = timezone.now() - timedelta(days=30)
                
                for course in instructor_courses.filter(status=Course.Status.PUBLISHED):
                    issues = []
                    severity = "low"  # low, medium, high
                    
                    # Get enrollment stats
                    total_course_enrollments = Enrollment.objects.filter(course=course).count()
                    active_course_enrollments = Enrollment.objects.filter(
                        course=course, 
                        status=Enrollment.Status.ACTIVE
                    ).count()
                    cancelled_enrollments = Enrollment.objects.filter(
                        course=course, 
                        status=Enrollment.Status.CANCELLED
                    ).count()
                    
                    # Issue 1: Low enrollment (published course with < 3 enrollments)
                    if total_course_enrollments < 3:
                        issues.append({
                            "type": "low_enrollment",
                            "message": f"Only {total_course_enrollments} enrollment(s)",
                            "suggestion": "Consider promoting this course or reviewing its description"
                        })
                        severity = "medium"
                    
                    # Issue 2: High attrition rate (> 30% cancelled/dropped)
                    if total_course_enrollments > 0:
                        attrition_rate = (cancelled_enrollments / total_course_enrollments) * 100
                        if attrition_rate > 30:
                            issues.append({
                                "type": "high_attrition",
                                "message": f"{round(attrition_rate)}% dropout rate",
                                "suggestion": "Review course content and gather student feedback"
                            })
                            severity = "high"
                    
                    # Issue 3: Stagnant engagement (no progress in 2 weeks)
                    recent_progress = LearnerProgress.objects.filter(
                        enrollment__course=course,
                        updated_at__gte=two_weeks_ago
                    ).exists()
                    
                    if active_course_enrollments > 0 and not recent_progress:
                        issues.append({
                            "type": "stagnant_engagement",
                            "message": "No student activity in 2 weeks",
                            "suggestion": "Send a reminder or add new engaging content"
                        })
                        if severity == "low":
                            severity = "medium"
                    
                    # Issue 4: Low completion rate (< 20% for courses with > 5 enrollments)
                    completed_enrollments = Enrollment.objects.filter(
                        course=course, 
                        status=Enrollment.Status.COMPLETED
                    ).count()
                    if total_course_enrollments >= 5:
                        completion_rate = (completed_enrollments / total_course_enrollments) * 100
                        if completion_rate < 20:
                            issues.append({
                                "type": "low_completion",
                                "message": f"Only {round(completion_rate)}% completion rate",
                                "suggestion": "Review course difficulty and structure"
                            })
                            if severity == "low":
                                severity = "medium"
                    
                    if issues:
                        courses_needing_attention.append({
                            "courseId": str(course.id),
                            "courseTitle": course.title,
                            "courseSlug": course.slug,
                            "enrollments": total_course_enrollments,
                            "activeEnrollments": active_course_enrollments,
                            "issues": issues,
                            "severity": severity
                        })
                
                # Sort by severity (high first, then medium, then low)
                severity_order = {"high": 0, "medium": 1, "low": 2}
                courses_needing_attention.sort(key=lambda x: severity_order.get(x['severity'], 3))
                courses_needing_attention = courses_needing_attention[:5]  # Limit to top 5
            except Exception as e:
                logger.warning(f"Error calculating courses needing attention: {e}")
            
            # At-risk students (no progress in 7+ days, low completion progress)
            at_risk_students = []
            try:
                seven_days_ago = timezone.now() - timedelta(days=7)
                
                # Get active enrollments with their last activity
                active_enrollments_qs = Enrollment.objects.filter(
                    course__instructor=user,
                    status=Enrollment.Status.ACTIVE
                ).select_related('user', 'course')
                
                for enrollment in active_enrollments_qs:
                    risk_factors = []
                    risk_level = "low"  # low, medium, high
                    
                    # Get last activity date
                    last_activity = LearnerProgress.objects.filter(
                        enrollment=enrollment
                    ).order_by('-updated_at').first()
                    
                    last_activity_date = last_activity.updated_at if last_activity else enrollment.enrolled_at
                    days_inactive = (timezone.now() - last_activity_date).days
                    
                    # Risk factor 1: No activity in 7+ days
                    if days_inactive >= 14:
                        risk_factors.append({
                            "type": "long_inactive",
                            "message": f"No activity for {days_inactive} days"
                        })
                        risk_level = "high"
                    elif days_inactive >= 7:
                        risk_factors.append({
                            "type": "inactive",
                            "message": f"No activity for {days_inactive} days"
                        })
                        risk_level = "medium"
                    
                    # Risk factor 2: Very low progress (< 20%) after 14+ days enrolled
                    days_enrolled = (timezone.now() - enrollment.enrolled_at).days
                    if days_enrolled >= 14 and enrollment.progress < 20:
                        risk_factors.append({
                            "type": "low_progress",
                            "message": f"Only {enrollment.progress}% complete after {days_enrolled} days"
                        })
                        if risk_level == "low":
                            risk_level = "medium"
                    
                    if risk_factors:
                        student_name = enrollment.user.get_full_name() or enrollment.user.email.split('@')[0]
                        at_risk_students.append({
                            "studentId": str(enrollment.user.id),
                            "studentName": student_name,
                            "studentEmail": enrollment.user.email,
                            "courseId": str(enrollment.course.id),
                            "courseTitle": enrollment.course.title,
                            "courseSlug": enrollment.course.slug,
                            "progress": enrollment.progress,
                            "lastActivity": last_activity_date.isoformat(),
                            "daysInactive": days_inactive,
                            "riskFactors": risk_factors,
                            "riskLevel": risk_level
                        })
                
                # Sort by risk level and days inactive
                risk_order = {"high": 0, "medium": 1, "low": 2}
                at_risk_students.sort(key=lambda x: (risk_order.get(x['riskLevel'], 3), -x['daysInactive']))
                at_risk_students = at_risk_students[:10]  # Limit to top 10
            except Exception as e:
                logger.warning(f"Error calculating at-risk students: {e}")
            
            # Urgent alerts (immediate action needed)
            urgent_alerts = []
            try:
                # Alert 1: Overdue grading (submissions older than 3 days)
                three_days_ago = timezone.now() - timedelta(days=3)
                overdue_grading = AssessmentAttempt.objects.filter(
                    assessment__course__instructor=user,
                    status=AssessmentAttempt.AttemptStatus.SUBMITTED,
                    end_time__lt=three_days_ago
                ).select_related('assessment__course', 'user')
                
                overdue_count = overdue_grading.count()
                if overdue_count > 0:
                    oldest_submission = overdue_grading.order_by('end_time').first()
                    days_overdue = (timezone.now() - oldest_submission.end_time).days
                    urgent_alerts.append({
                        "type": "overdue_grading",
                        "severity": "high",
                        "title": f"{overdue_count} submission(s) awaiting grading",
                        "message": f"Oldest submission is {days_overdue} days old",
                        "actionUrl": "/instructor/grading",
                        "actionLabel": "Go to Grading"
                    })
                
                # Alert 2: Assessments with upcoming deadlines (within 48 hours)
                forty_eight_hours = timezone.now() + timedelta(hours=48)
                today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
                upcoming_assessments = Assessment.objects.filter(
                    course__instructor=user,
                    due_date__lte=forty_eight_hours,
                    due_date__gte=today_start
                ).select_related('course')
                
                for assessment in upcoming_assessments[:3]:  # Limit to 3
                    urgent_alerts.append({
                        "type": "upcoming_deadline",
                        "severity": "medium",
                        "title": f"'{assessment.title}' deadline approaching",
                        "message": f"Due on {assessment.due_date.strftime('%b %d, %Y')} for {assessment.course.title}",
                        "actionUrl": f"/instructor/courses/{assessment.course.slug}/assessments",
                        "actionLabel": "View Assessment"
                    })
                
                # Alert 3: Courses with no recent content updates (published > 30 days, no updates)
                thirty_days_ago = timezone.now() - timedelta(days=30)
                stale_courses = instructor_courses.filter(
                    status=Course.Status.PUBLISHED,
                    updated_at__lt=thirty_days_ago
                )
                
                if stale_courses.count() > 0:
                    course_list = ", ".join([c.title for c in stale_courses[:2]])
                    urgent_alerts.append({
                        "type": "stale_content",
                        "severity": "low",
                        "title": f"{stale_courses.count()} course(s) haven't been updated recently",
                        "message": f"Consider refreshing: {course_list}",
                        "actionUrl": "/instructor/courses",
                        "actionLabel": "View Courses"
                    })
                
            except Exception as e:
                logger.warning(f"Error calculating urgent alerts: {e}")

            # Revenue data from RevenueAnalytics
            revenue_data = {
                "thisMonth": 0,
                "total": 0,
                "avgPerCourse": 0,
                "growth": 0
            }
            try:
                # Get current month boundaries
                now = timezone.now()
                month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                
                # Get revenue analytics for this instructor
                instructor_revenue = RevenueAnalytics.objects.filter(
                    instructor=user
                ).order_by('-period_end')
                
                # Calculate total revenue across all records
                total_revenue = instructor_revenue.aggregate(
                    total=Sum('total_revenue')
                )['total'] or 0
                
                # Get this month's revenue (records where period covers this month)
                this_month_revenue = instructor_revenue.filter(
                    period_start__lte=now.date(),
                    period_end__gte=month_start.date()
                ).aggregate(
                    monthly=Sum('monthly_revenue')
                )['monthly'] or 0
                
                # Calculate average per course
                course_count = instructor_courses.count()
                avg_per_course = float(total_revenue) / course_count if course_count > 0 else 0
                
                # Get growth rate from most recent record
                latest_revenue = instructor_revenue.first()
                growth_rate = float(latest_revenue.growth_rate) if latest_revenue else 0
                
                revenue_data = {
                    "thisMonth": float(this_month_revenue),
                    "total": float(total_revenue),
                    "avgPerCourse": round(avg_per_course, 2),
                    "growth": round(growth_rate, 1)
                }
            except Exception as e:
                logger.warning(f"Error calculating revenue data: {e}")

            # Content progress data (simplified)
            content_progress = {
                "drafts": draft_courses,
                "publishedThisMonth": 0,
                "modulesCreated": 0,
                "contentItems": 0
            }

            stats = {
                "totalCourses": total_courses,
                "publishedCourses": published_courses,
                "draftCourses": draft_courses,
                "totalEnrollments": total_enrollments,
                "activeEnrollments": active_enrollments,
                "activeStudents": active_students,
                "pendingGrading": pending_grading,
                "avgCompletionRate": avg_completion_rate,
                "recentAssessments": recent_assessments_data,
                "recentActivity": recent_activity,
                "upcomingDeadlines": upcoming_deadlines,
                "topCourses": top_courses,
                "topStudents": top_students,
                "revenue": revenue_data,
                "contentProgress": content_progress,
                # Proactive dashboard metrics
                "coursesNeedingAttention": courses_needing_attention,
                "atRiskStudents": at_risk_students,
                "urgentAlerts": urgent_alerts
            }
            return Response(stats)
        except Exception as e:
            logger.error(f"Error generating instructor dashboard stats for user {user.id}: {e}", exc_info=True)
            return Response({"detail": "Could not retrieve dashboard statistics."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(tags=['Admin - Tenants'])
class TenantListView(generics.ListAPIView):
    """
    List tenants (admin only).
    - Superusers see all active tenants
    - Tenant admins see only their own tenant
    """
    serializer_class = TenantSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return Tenant.objects.filter(is_active=True).order_by('name')
        # Tenant admins see only their own tenant
        tenant = getattr(user, 'tenant', None)
        if tenant:
            return Tenant.objects.filter(id=tenant.id, is_active=True)
        return Tenant.objects.none()


@extend_schema(tags=['Admin - Tenants'])
class TenantStatsView(APIView):
    """
    Get overview statistics for tenants (admin only).
    - Superusers see platform-wide stats across all tenants
    - Tenant admins see stats for their own tenant only
    """
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    
    def get(self, request):
        user = request.user
        
        # Import here to avoid circular imports
        from apps.users.models import User
        from apps.courses.models import Course
        from apps.enrollments.models import Enrollment
        
        thirty_days_ago = timezone.now() - timedelta(days=30)
        
        # Determine tenant scope
        is_platform_admin = user.is_superuser
        tenant = None if is_platform_admin else getattr(user, 'tenant', None)
        
        if is_platform_admin:
            # Superusers see all data
            stats = {
                'total_tenants': Tenant.objects.count(),
                'active_tenants': Tenant.objects.filter(is_active=True).count(),
                'total_users': User.objects.count(),
                'total_courses': Course.objects.count(),
                'total_enrollments': Enrollment.objects.count(),
                'active_users_30d': User.objects.filter(
                    last_login__gte=thirty_days_ago
                ).count(),
                'tenant_breakdown': list(
                    Tenant.objects.annotate(
                        user_count=Count('users'),
                        course_count=Count('courses')
                    ).values('id', 'name', 'slug', 'is_active', 'user_count', 'course_count')
                    .order_by('-user_count')[:10]
                ),
                'is_platform_admin': True,
            }
        elif tenant:
            # Tenant admins see only their tenant's data
            stats = {
                'total_tenants': 1,
                'active_tenants': 1 if tenant.is_active else 0,
                'total_users': User.objects.filter(tenant=tenant).count(),
                'total_courses': Course.objects.filter(tenant=tenant).count(),
                'total_enrollments': Enrollment.objects.filter(course__tenant=tenant).count(),
                'active_users_30d': User.objects.filter(
                    tenant=tenant,
                    last_login__gte=thirty_days_ago
                ).count(),
                'tenant_breakdown': list(
                    Tenant.objects.filter(id=tenant.id).annotate(
                        user_count=Count('users'),
                        course_count=Count('courses')
                    ).values('id', 'name', 'slug', 'is_active', 'user_count', 'course_count')
                ),
                'is_platform_admin': False,
            }
        else:
            # No tenant associated - return empty stats
            return Response(
                {"detail": "No tenant associated with this user."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        return Response(stats)


@extend_schema(tags=['Admin - Tenants'])
class TenantDomainListView(generics.ListAPIView):
    """
    List domains for a specific tenant (admin only).
    - Superusers can view domains for any tenant
    - Tenant admins can only view domains for their own tenant
    """
    serializer_class = TenantDomainSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    
    def get_queryset(self):
        user = self.request.user
        tenant_id = self.kwargs.get('tenant_id')
        
        if not tenant_id:
            return TenantDomain.objects.none()
        
        # Superusers can view any tenant's domains
        if user.is_superuser:
            return TenantDomain.objects.filter(tenant_id=tenant_id).order_by('-is_primary', 'domain')
        
        # Tenant admins can only view their own tenant's domains
        user_tenant = getattr(user, 'tenant', None)
        if user_tenant and str(user_tenant.id) == str(tenant_id):
            return TenantDomain.objects.filter(tenant_id=tenant_id).order_by('-is_primary', 'domain')
        
        return TenantDomain.objects.none()


class InstructorReportsView(APIView):
    """
    Provides report definitions accessible to instructors.
    Returns reports that instructors can use to analyze their courses and students.
    """
    permission_classes = [IsAuthenticated, IsInstructorOrAdmin]

    def get(self, request, format=None):
        user = request.user
        tenant = request.tenant
        
        try:
            # Get reports that are accessible to instructors
            # This includes:
            # 1. Reports specifically for instructors (config contains access_level='INSTRUCTOR')
            # 2. Reports that belong to the current tenant or are system-wide (tenant=None)
            
            report_query = Q()
            
            # Add tenant filtering - include system-wide reports (tenant=None) and tenant-specific
            if tenant:
                report_query &= (Q(tenant=tenant) | Q(tenant__isnull=True))
            else:
                report_query &= Q(tenant__isnull=True)
            
            # Filter by instructor-relevant slugs
            instructor_relevant_slugs = [
                'student-progress',
                'course-completion',
                'assessment-results',
                'engagement-metrics',
                'course-analytics',
                'student-performance'
            ]
            
            reports = Report.objects.filter(
                report_query & Q(slug__in=instructor_relevant_slugs)
            ).select_related('tenant').order_by('name')
            
            # Serialize the reports
            serializer = InstructorReportSerializer(reports, many=True)
            return Response(serializer.data)
            
        except Exception as e:
            logger.error(f"Error retrieving instructor reports for user {user.id}: {e}", exc_info=True)
            return Response({"detail": "Could not retrieve reports."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# --- LTI Views ---


class LTIOIDCLoginView(APIView):
    """
    Handles LTI 1.3 OIDC login initiation (Step 1 of LTI launch).
    The platform redirects here with initial login request parameters.
    """

    permission_classes = []  # No authentication required
    authentication_classes = []  # Disable authentication

    @extend_schema(
        tags=["LTI"],
        description="Initiates the LTI 1.3 OIDC login flow",
        responses={302: OpenApiTypes.STR},
    )
    def get(self, request):
        return self._handle_oidc_login(request)

    def post(self, request):
        return self._handle_oidc_login(request)

    def _handle_oidc_login(self, request):
        from django.http import HttpResponseRedirect

        from .models import LTIPlatform
        from .services import LTIService, LTIServiceError

        try:
            # Get platform from request parameters
            iss = request.GET.get("iss") or request.POST.get("iss")
            client_id = request.GET.get("client_id") or request.POST.get("client_id")

            if not iss:
                return Response(
                    {"error": "Missing 'iss' parameter"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Find the platform configuration
            query = LTIPlatform.objects.filter(issuer=iss, is_active=True)
            tenant = getattr(request, "tenant", None)
            if tenant:
                query = query.filter(tenant=tenant)
            if client_id:
                query = query.filter(client_id=client_id)

            platform = query.first()
            if not platform:
                logger.warning(f"LTI platform not found: iss={iss}, client_id={client_id}")
                return Response(
                    {"error": "LTI platform not configured"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Initiate OIDC login
            lti_service = LTIService(request, platform=platform)
            redirect_url = lti_service.validate_oidc_login()

            return HttpResponseRedirect(redirect_url)

        except LTIServiceError as e:
            logger.error(f"LTI OIDC login error: {e}")
            return Response(
                {"error": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Unexpected LTI OIDC login error: {e}", exc_info=True)
            return Response(
                {"error": "An error occurred during LTI login"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class LTILaunchView(APIView):
    """
    Handles the LTI 1.3 launch callback (Step 2 - after OIDC authentication).
    Validates the launch, provisions user/enrollment, and redirects to the LMS.
    """

    permission_classes = []
    authentication_classes = []

    @extend_schema(
        tags=["LTI"],
        description="Processes LTI 1.3 launch request after OIDC authentication",
        responses={302: OpenApiTypes.STR},
    )
    def post(self, request):
        from django.http import HttpResponseRedirect
        from rest_framework_simplejwt.tokens import RefreshToken

        from .services import LTIService, LTIServiceError

        try:
            # Validate the launch
            lti_service = LTIService(request)
            launch_data = lti_service.validate_launch()

            # Provision user and enrollment
            user, course, enrollment = lti_service.provision_user_and_enrollment(
                launch_data
            )

            # Generate JWT tokens for the user
            refresh = RefreshToken.for_user(user)
            access_token = str(refresh.access_token)

            # Determine redirect URL
            if lti_service.is_deep_linking_request():
                # Deep linking - redirect to content selection UI
                redirect_url = f"/lti/deep-link?token={access_token}"
            elif course:
                # Regular launch with linked course
                redirect_url = f"/courses/{course.id}?token={access_token}"
            else:
                # No course linked - redirect to dashboard
                redirect_url = f"/dashboard?token={access_token}"

            # Build full frontend URL
            frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:3000")
            full_redirect_url = f"{frontend_url}{redirect_url}"

            logger.info(
                f"LTI launch successful for user {user.email}, redirecting to {redirect_url}"
            )
            return HttpResponseRedirect(full_redirect_url)

        except LTIServiceError as e:
            logger.error(f"LTI launch error: {e}")
            return Response(
                {"error": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Unexpected LTI launch error: {e}", exc_info=True)
            return Response(
                {"error": "An error occurred during LTI launch"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class LTIJWKSView(APIView):
    """
    Serves the public JSON Web Key Set (JWKS) for LTI tool verification.
    Platforms use this to verify signatures from our tool.
    """

    permission_classes = []
    authentication_classes = []

    @extend_schema(
        tags=["LTI"],
        description="Returns the public JWKS for LTI platform verification",
    )
    def get(self, request, platform_id=None):
        import json

        from .models import LTIPlatform

        try:
            # If platform_id provided, return specific platform's key
            if platform_id:
                try:
                    platform = LTIPlatform.objects.get(id=platform_id, is_active=True)
                    # Parse the public key and convert to JWKS format
                    from cryptography.hazmat.primitives import serialization
                    from cryptography.hazmat.primitives.asymmetric import rsa

                    public_key = serialization.load_pem_public_key(
                        platform.tool_public_key.encode()
                    )
                    # Convert to JWK format
                    from jwt.algorithms import RSAAlgorithm

                    jwk = json.loads(RSAAlgorithm.to_jwk(public_key))
                    jwk["use"] = "sig"
                    jwk["kid"] = str(platform.id)

                    return Response({"keys": [jwk]})
                except LTIPlatform.DoesNotExist:
                    return Response(
                        {"error": "Platform not found"},
                        status=status.HTTP_404_NOT_FOUND,
                    )
            else:
                # Return all active platform keys
                tenant = getattr(request, "tenant", None)
                query = LTIPlatform.objects.filter(is_active=True)
                if tenant:
                    query = query.filter(tenant=tenant)

                keys = []
                for platform in query:
                    try:
                        from cryptography.hazmat.primitives import serialization
                        from jwt.algorithms import RSAAlgorithm

                        public_key = serialization.load_pem_public_key(
                            platform.tool_public_key.encode()
                        )
                        jwk = json.loads(RSAAlgorithm.to_jwk(public_key))
                        jwk["use"] = "sig"
                        jwk["kid"] = str(platform.id)
                        keys.append(jwk)
                    except Exception as e:
                        logger.warning(
                            f"Failed to load public key for platform {platform.id}: {e}"
                        )

                return Response({"keys": keys})

        except Exception as e:
            logger.error(f"Error generating JWKS: {e}", exc_info=True)
            return Response(
                {"error": "Failed to generate JWKS"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# --- SSO Views ---


class SSOLoginView(APIView):
    """
    Initiates SSO login for a tenant.
    Supports both SAML and OAuth providers.
    """

    permission_classes = []
    authentication_classes = []

    @extend_schema(
        tags=["SSO"],
        description="Initiates SSO login flow",
        responses={302: OpenApiTypes.STR},
    )
    def get(self, request):
        from django.http import HttpResponseRedirect

        from .models import SSOConfiguration
        from .services import SSOService, SSOServiceError

        try:
            # Get SSO configuration
            config_id = request.GET.get("config_id")
            provider_type = request.GET.get("provider")
            relay_state = request.GET.get("next", "/")

            tenant = getattr(request, "tenant", None)
            if not tenant:
                return Response(
                    {"error": "Tenant context required for SSO"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Find the SSO configuration
            if config_id:
                try:
                    sso_config = SSOConfiguration.objects.get(
                        id=config_id, tenant=tenant, is_active=True
                    )
                except SSOConfiguration.DoesNotExist:
                    return Response(
                        {"error": "SSO configuration not found"},
                        status=status.HTTP_404_NOT_FOUND,
                    )
            elif provider_type:
                sso_config = SSOConfiguration.objects.filter(
                    tenant=tenant,
                    provider_type=provider_type.upper(),
                    is_active=True,
                ).first()
                if not sso_config:
                    return Response(
                        {"error": f"SSO provider '{provider_type}' not configured"},
                        status=status.HTTP_404_NOT_FOUND,
                    )
            else:
                # Use default SSO config for tenant
                sso_config = SSOConfiguration.objects.filter(
                    tenant=tenant, is_default=True, is_active=True
                ).first()
                if not sso_config:
                    sso_config = SSOConfiguration.objects.filter(
                        tenant=tenant, is_active=True
                    ).first()
                if not sso_config:
                    return Response(
                        {"error": "No SSO configuration found for this tenant"},
                        status=status.HTTP_404_NOT_FOUND,
                    )

            # Initiate SSO based on provider type
            sso_service = SSOService(request, sso_config=sso_config)

            if sso_config.provider_type == SSOConfiguration.ProviderType.SAML:
                redirect_url = sso_service.initiate_saml_login(relay_state=relay_state)
            else:
                # OAuth/OIDC
                redirect_url = sso_service.get_oauth_redirect_url()

            return HttpResponseRedirect(redirect_url)

        except SSOServiceError as e:
            logger.error(f"SSO login error: {e}")
            return Response(
                {"error": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Unexpected SSO login error: {e}", exc_info=True)
            return Response(
                {"error": "An error occurred during SSO login"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class SAMLACSView(APIView):
    """
    SAML Assertion Consumer Service (ACS) endpoint.
    Receives and processes SAML responses from the IdP.
    """

    permission_classes = []
    authentication_classes = []

    @extend_schema(
        tags=["SSO"],
        description="Processes SAML assertion response from IdP",
        responses={302: OpenApiTypes.STR},
    )
    def post(self, request):
        from django.http import HttpResponseRedirect
        from rest_framework_simplejwt.tokens import RefreshToken

        from .models import SSOConfiguration
        from .services import SSOService, SSOServiceError

        try:
            tenant = getattr(request, "tenant", None)
            if not tenant:
                return Response(
                    {"error": "Tenant context required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Find SAML configuration for this tenant
            sso_config = SSOConfiguration.objects.filter(
                tenant=tenant,
                provider_type=SSOConfiguration.ProviderType.SAML,
                is_active=True,
            ).first()

            if not sso_config:
                return Response(
                    {"error": "SAML not configured for this tenant"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Process SAML response
            sso_service = SSOService(request, sso_config=sso_config)
            user, relay_state = sso_service.process_saml_response()

            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)
            access_token = str(refresh.access_token)

            # Redirect to frontend with token
            frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:3000")
            redirect_path = relay_state or "/"
            full_redirect_url = f"{frontend_url}{redirect_path}?token={access_token}"

            logger.info(f"SAML authentication successful for user {user.email}")
            return HttpResponseRedirect(full_redirect_url)

        except SSOServiceError as e:
            logger.error(f"SAML ACS error: {e}")
            return Response(
                {"error": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Unexpected SAML ACS error: {e}", exc_info=True)
            return Response(
                {"error": "An error occurred processing SAML response"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class SAMLMetadataView(APIView):
    """
    Serves the Service Provider (SP) SAML metadata XML.
    IdPs use this to configure trust with our SP.
    """

    permission_classes = []
    authentication_classes = []

    @extend_schema(
        tags=["SSO"],
        description="Returns SAML SP metadata XML",
    )
    def get(self, request, config_id=None):
        from django.http import HttpResponse

        from .models import SSOConfiguration
        from .services import SSOService, SSOServiceError

        try:
            tenant = getattr(request, "tenant", None)

            if config_id:
                try:
                    sso_config = SSOConfiguration.objects.get(
                        id=config_id,
                        provider_type=SSOConfiguration.ProviderType.SAML,
                        is_active=True,
                    )
                    if tenant and sso_config.tenant != tenant:
                        return Response(
                            {"error": "Configuration not found"},
                            status=status.HTTP_404_NOT_FOUND,
                        )
                except SSOConfiguration.DoesNotExist:
                    return Response(
                        {"error": "SAML configuration not found"},
                        status=status.HTTP_404_NOT_FOUND,
                    )
            else:
                if not tenant:
                    return Response(
                        {"error": "Tenant context required"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                sso_config = SSOConfiguration.objects.filter(
                    tenant=tenant,
                    provider_type=SSOConfiguration.ProviderType.SAML,
                    is_active=True,
                ).first()
                if not sso_config:
                    return Response(
                        {"error": "SAML not configured for this tenant"},
                        status=status.HTTP_404_NOT_FOUND,
                    )

            sso_service = SSOService(request, sso_config=sso_config)
            metadata_xml = sso_service.get_saml_metadata()

            return HttpResponse(metadata_xml, content_type="application/xml")

        except SSOServiceError as e:
            logger.error(f"SAML metadata error: {e}")
            return Response(
                {"error": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Unexpected SAML metadata error: {e}", exc_info=True)
            return Response(
                {"error": "An error occurred generating SAML metadata"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class SAMLSLSView(APIView):
    """
    SAML Single Logout Service (SLS) endpoint.
    Handles both SP-initiated and IdP-initiated logout.
    """

    permission_classes = []
    authentication_classes = []

    @extend_schema(
        tags=["SSO"],
        description="Processes SAML Single Logout (via GET redirect binding)",
        responses={302: OpenApiTypes.STR},
    )
    def get(self, request, config_id=None):
        """Handle SAML logout via HTTP-Redirect binding."""
        return self._process_slo(request, config_id)

    @extend_schema(
        tags=["SSO"],
        description="Processes SAML Single Logout (via POST binding)",
        responses={302: OpenApiTypes.STR},
    )
    def post(self, request, config_id=None):
        """Handle SAML logout via HTTP-POST binding."""
        return self._process_slo(request, config_id)

    def _process_slo(self, request, config_id=None):
        from django.http import HttpResponseRedirect
        from django.contrib.auth import logout as django_logout

        from .models import SSOConfiguration
        from .services import SSOService, SSOServiceError

        try:
            tenant = getattr(request, "tenant", None)

            # Resolve the SSO configuration
            if config_id:
                try:
                    sso_config = SSOConfiguration.objects.get(
                        id=config_id,
                        provider_type=SSOConfiguration.ProviderType.SAML,
                        is_active=True,
                    )
                    if tenant and sso_config.tenant != tenant:
                        return Response(
                            {"error": "Configuration not found"},
                            status=status.HTTP_404_NOT_FOUND,
                        )
                except SSOConfiguration.DoesNotExist:
                    return Response(
                        {"error": "SAML configuration not found"},
                        status=status.HTTP_404_NOT_FOUND,
                    )
            else:
                if not tenant:
                    return Response(
                        {"error": "Tenant context required"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                sso_config = SSOConfiguration.objects.filter(
                    tenant=tenant,
                    provider_type=SSOConfiguration.ProviderType.SAML,
                    is_active=True,
                ).first()
                if not sso_config:
                    return Response(
                        {"error": "SAML not configured for this tenant"},
                        status=status.HTTP_404_NOT_FOUND,
                    )

            sso_service = SSOService(request, sso_config=sso_config)
            redirect_url = sso_service.process_saml_logout()

            # Perform local logout (invalidate Django session)
            if request.user.is_authenticated:
                django_logout(request)
                logger.info(f"Local session invalidated for user during SAML SLO")

            # Redirect to the URL returned by the IdP, or to home
            final_redirect = redirect_url or "/"
            logger.info(f"SAML SLO complete, redirecting to: {final_redirect}")
            return HttpResponseRedirect(final_redirect)

        except SSOServiceError as e:
            logger.error(f"SAML SLO error: {e}")
            return Response(
                {"error": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Unexpected SAML SLO error: {e}", exc_info=True)
            return Response(
                {"error": "An error occurred processing SAML logout"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class SAMLLogoutView(APIView):
    """
    Initiates SP-initiated SAML Single Logout.
    Requires authentication. Redirects to IdP for logout.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["SSO"],
        description="Initiates SAML Single Logout from the Service Provider",
        parameters=[
            OpenApiParameter(
                name="config_id",
                description="Optional SSO configuration ID",
                required=False,
                type=str,
            ),
        ],
        responses={302: OpenApiTypes.STR},
    )
    def post(self, request):
        from django.http import HttpResponseRedirect

        from .models import SSOConfiguration
        from .services import SSOService, SSOServiceError

        try:
            tenant = getattr(request, "tenant", None)
            config_id = request.data.get("config_id")

            # Resolve the SSO configuration
            if config_id:
                try:
                    sso_config = SSOConfiguration.objects.get(
                        id=config_id,
                        provider_type=SSOConfiguration.ProviderType.SAML,
                        is_active=True,
                    )
                    if tenant and sso_config.tenant != tenant:
                        return Response(
                            {"error": "Configuration not found"},
                            status=status.HTTP_404_NOT_FOUND,
                        )
                except SSOConfiguration.DoesNotExist:
                    return Response(
                        {"error": "SAML configuration not found"},
                        status=status.HTTP_404_NOT_FOUND,
                    )
            else:
                if not tenant:
                    return Response(
                        {"error": "Tenant context required or provide config_id"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                sso_config = SSOConfiguration.objects.filter(
                    tenant=tenant,
                    provider_type=SSOConfiguration.ProviderType.SAML,
                    is_active=True,
                ).first()
                if not sso_config:
                    return Response(
                        {"error": "SAML not configured for this tenant"},
                        status=status.HTTP_404_NOT_FOUND,
                    )

            # Get SAML session info if stored (name_id, session_index)
            # These would typically be stored in the session during login
            name_id = request.session.get("saml_name_id")
            session_index = request.session.get("saml_session_index")

            sso_service = SSOService(request, sso_config=sso_config)
            redirect_url = sso_service.initiate_saml_logout(
                name_id=name_id,
                session_index=session_index,
            )

            logger.info(f"SP-initiated SAML logout for user: {request.user.email}")
            return HttpResponseRedirect(redirect_url)

        except SSOServiceError as e:
            logger.error(f"SAML logout initiation error: {e}")
            return Response(
                {"error": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Unexpected SAML logout error: {e}", exc_info=True)
            return Response(
                {"error": "An error occurred initiating SAML logout"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class OAuthCallbackView(APIView):
    """
    OAuth callback endpoint.
    Receives the authorization code from the OAuth provider.
    """

    permission_classes = []
    authentication_classes = []

    @extend_schema(
        tags=["SSO"],
        description="Processes OAuth callback after user authorization",
        responses={302: OpenApiTypes.STR},
    )
    def get(self, request):
        from django.http import HttpResponseRedirect
        from rest_framework_simplejwt.tokens import RefreshToken

        from .services import SSOService, SSOServiceError

        try:
            # Process OAuth callback
            sso_service = SSOService(request)
            user, redirect_path = sso_service.process_oauth_callback()

            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)
            access_token = str(refresh.access_token)

            # Redirect to frontend with token
            frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:3000")
            full_redirect_url = f"{frontend_url}{redirect_path}?token={access_token}"

            logger.info(f"OAuth authentication successful for user {user.email}")
            return HttpResponseRedirect(full_redirect_url)

        except SSOServiceError as e:
            logger.error(f"OAuth callback error: {e}")
            # Redirect to frontend with error
            frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:3000")
            return HttpResponseRedirect(f"{frontend_url}/login?error={str(e)}")
        except Exception as e:
            logger.error(f"Unexpected OAuth callback error: {e}", exc_info=True)
            frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:3000")
            return HttpResponseRedirect(
                f"{frontend_url}/login?error=An error occurred during authentication"
            )


class SSOProvidersView(APIView):
    """
    Lists available SSO providers for a tenant.
    Used by the frontend to show SSO login options.
    """

    permission_classes = []
    authentication_classes = []

    @extend_schema(
        tags=["SSO"],
        description="Lists available SSO providers for the current tenant",
    )
    def get(self, request):
        from .models import SSOConfiguration

        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"providers": []})

        providers = SSOConfiguration.objects.filter(
            tenant=tenant, is_active=True
        ).values("id", "name", "provider_type", "is_default")

        return Response(
            {
                "providers": [
                    {
                        "id": str(p["id"]),
                        "name": p["name"],
                        "type": p["provider_type"],
                        "is_default": p["is_default"],
                    }
                    for p in providers
                ]
            }
        )


# --- LTI AGS (Assignment & Grade Services) Views ---


class LTIResourceLinkListView(generics.ListAPIView):
    """
    Lists LTI resource links for the current tenant.
    Instructors and admins can view resource links for courses they have access to.
    """
    permission_classes = [IsAuthenticated, IsInstructorOrAdmin]

    @extend_schema(
        tags=["LTI AGS"],
        description="List LTI resource links for courses the user has access to",
    )
    def get(self, request, *args, **kwargs):
        from .models import LTIResourceLink
        from .serializers import LTIResourceLinkSerializer

        user = request.user
        tenant = getattr(request, "tenant", None)

        # Build query for resource links
        query = LTIResourceLink.objects.select_related('platform', 'course')

        if tenant:
            query = query.filter(platform__tenant=tenant)

        # Non-admin users only see links for their courses
        if not user.is_superuser and not user.is_staff:
            query = query.filter(course__instructor=user)

        # Optional filtering
        platform_id = request.query_params.get('platform_id')
        course_id = request.query_params.get('course_id')

        if platform_id:
            query = query.filter(platform_id=platform_id)
        if course_id:
            query = query.filter(course_id=course_id)

        serializer = LTIResourceLinkSerializer(query, many=True)
        return Response(serializer.data)


class LTIResourceLinkDetailView(APIView):
    """
    Retrieve, update, or delete an LTI resource link.
    Main use case: linking/unlinking a course to a resource link.
    """
    permission_classes = [IsAuthenticated, IsInstructorOrAdmin]

    def get_resource_link(self, resource_link_id, user, tenant):
        from .models import LTIResourceLink

        try:
            query = LTIResourceLink.objects.select_related('platform', 'course')

            if tenant:
                query = query.filter(platform__tenant=tenant)

            resource_link = query.get(id=resource_link_id)

            # Non-admin users can only access their own courses
            if not user.is_superuser and not user.is_staff:
                if resource_link.course and resource_link.course.instructor != user:
                    return None

            return resource_link
        except LTIResourceLink.DoesNotExist:
            return None

    @extend_schema(
        tags=["LTI AGS"],
        description="Retrieve details of an LTI resource link",
    )
    def get(self, request, resource_link_id):
        from .serializers import LTIResourceLinkSerializer

        tenant = getattr(request, "tenant", None)
        resource_link = self.get_resource_link(resource_link_id, request.user, tenant)

        if not resource_link:
            return Response(
                {"error": "Resource link not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = LTIResourceLinkSerializer(resource_link)
        return Response(serializer.data)

    @extend_schema(
        tags=["LTI AGS"],
        description="Update an LTI resource link (e.g., link/unlink a course)",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "course": {"type": "string", "format": "uuid", "nullable": True},
                },
            }
        },
    )
    def patch(self, request, resource_link_id):
        from .serializers import LTIResourceLinkSerializer
        from apps.courses.models import Course

        tenant = getattr(request, "tenant", None)
        resource_link = self.get_resource_link(resource_link_id, request.user, tenant)

        if not resource_link:
            return Response(
                {"error": "Resource link not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Handle course linking/unlinking
        if "course" in request.data:
            course_id = request.data.get("course")
            if course_id is None:
                # Unlink course
                resource_link.course = None
                logger.info(f"Unlinked course from resource link {resource_link_id}")
            else:
                # Link course
                try:
                    course = Course.objects.get(id=course_id)

                    # Verify user has access to this course
                    if not request.user.is_superuser and not request.user.is_staff:
                        if course.instructor != request.user:
                            return Response(
                                {"error": "You don't have access to this course"},
                                status=status.HTTP_403_FORBIDDEN
                            )

                    # Verify course belongs to same tenant
                    if tenant and course.tenant != tenant:
                        return Response(
                            {"error": "Course not found"},
                            status=status.HTTP_404_NOT_FOUND
                        )

                    resource_link.course = course
                    logger.info(f"Linked course {course_id} to resource link {resource_link_id}")
                except Course.DoesNotExist:
                    return Response(
                        {"error": "Course not found"},
                        status=status.HTTP_404_NOT_FOUND
                    )

        resource_link.save()
        serializer = LTIResourceLinkSerializer(resource_link)
        return Response(serializer.data)

    @extend_schema(
        tags=["LTI AGS"],
        description="Delete an LTI resource link (admin only)",
    )
    def delete(self, request, resource_link_id):
        # Only admins can delete resource links
        if not request.user.is_superuser and not request.user.is_staff:
            return Response(
                {"error": "Only administrators can delete resource links"},
                status=status.HTTP_403_FORBIDDEN
            )

        tenant = getattr(request, "tenant", None)
        resource_link = self.get_resource_link(resource_link_id, request.user, tenant)

        if not resource_link:
            return Response(
                {"error": "Resource link not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Check for associated line items and warn
        line_items_count = resource_link.line_items.count()
        if line_items_count > 0:
            logger.warning(
                f"Deleting resource link {resource_link_id} with {line_items_count} line items"
            )

        resource_link.delete()
        logger.info(f"Deleted resource link {resource_link_id}")

        return Response(status=status.HTTP_204_NO_CONTENT)


class LTILineItemListView(generics.ListCreateAPIView):
    """
    Lists and creates LTI line items for grade passback.
    """
    permission_classes = [IsAuthenticated, IsInstructorOrAdmin]

    @extend_schema(
        tags=["LTI AGS"],
        description="List LTI line items for resource links",
    )
    def get(self, request, *args, **kwargs):
        from .models import LTILineItem
        from .serializers import LTILineItemListSerializer

        user = request.user
        tenant = getattr(request, "tenant", None)

        query = LTILineItem.objects.select_related(
            'resource_link', 'resource_link__platform', 'assessment'
        )

        if tenant:
            query = query.filter(resource_link__platform__tenant=tenant)

        # Non-admin users only see line items for their courses
        if not user.is_superuser and not user.is_staff:
            query = query.filter(resource_link__course__instructor=user)

        # Optional filtering
        resource_link_id = request.query_params.get('resource_link_id')
        assessment_id = request.query_params.get('assessment_id')

        if resource_link_id:
            query = query.filter(resource_link_id=resource_link_id)
        if assessment_id:
            query = query.filter(assessment_id=assessment_id)

        serializer = LTILineItemListSerializer(query.order_by('-created_at'), many=True)
        return Response(serializer.data)

    @extend_schema(
        tags=["LTI AGS"],
        description="Create a new LTI line item",
    )
    def post(self, request, *args, **kwargs):
        from .models import LTILineItem
        from .serializers import LTILineItemCreateSerializer, LTILineItemSerializer
        from .services import AGSService, AGSServiceError

        serializer = LTILineItemCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Verify user has access to this resource link's course
        resource_link = serializer.validated_data['resource_link']
        user = request.user
        if not user.is_superuser and not user.is_staff:
            if resource_link.course and resource_link.course.instructor != user:
                return Response(
                    {"error": "You don't have permission to create line items for this resource link."},
                    status=status.HTTP_403_FORBIDDEN
                )

        # Create line item locally
        line_item = serializer.save()

        # Optionally sync with LTI platform
        try:
            ags_service = AGSService(resource_link.platform)
            ags_service.create_or_get_line_item(
                resource_link=resource_link,
                label=line_item.label,
                score_maximum=float(line_item.score_maximum),
                tag=line_item.tag,
                resource_id=line_item.resource_id,
            )
            line_item.refresh_from_db()
        except AGSServiceError as e:
            logger.warning(f"Failed to sync line item with platform: {e}")
            # Line item is still created locally

        return Response(
            LTILineItemSerializer(line_item).data,
            status=status.HTTP_201_CREATED
        )


class LTILineItemDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update, or delete an LTI line item.
    """
    permission_classes = [IsAuthenticated, IsInstructorOrAdmin]

    @extend_schema(
        tags=["LTI AGS"],
        description="Get LTI line item details",
    )
    def get(self, request, line_item_id, *args, **kwargs):
        from .models import LTILineItem
        from .serializers import LTILineItemSerializer

        try:
            line_item = LTILineItem.objects.select_related(
                'resource_link', 'assessment'
            ).get(id=line_item_id)
        except LTILineItem.DoesNotExist:
            return Response(
                {"error": "Line item not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Check permissions
        user = request.user
        if not user.is_superuser and not user.is_staff:
            if line_item.resource_link.course and line_item.resource_link.course.instructor != user:
                return Response(
                    {"error": "You don't have permission to view this line item."},
                    status=status.HTTP_403_FORBIDDEN
                )

        return Response(LTILineItemSerializer(line_item).data)

    @extend_schema(
        tags=["LTI AGS"],
        description="Update an LTI line item",
    )
    def patch(self, request, line_item_id, *args, **kwargs):
        from .models import LTILineItem
        from .serializers import LTILineItemSerializer

        try:
            line_item = LTILineItem.objects.get(id=line_item_id)
        except LTILineItem.DoesNotExist:
            return Response(
                {"error": "Line item not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Check permissions
        user = request.user
        if not user.is_superuser and not user.is_staff:
            if line_item.resource_link.course and line_item.resource_link.course.instructor != user:
                return Response(
                    {"error": "You don't have permission to update this line item."},
                    status=status.HTTP_403_FORBIDDEN
                )

        serializer = LTILineItemSerializer(line_item, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data)

    @extend_schema(
        tags=["LTI AGS"],
        description="Delete an LTI line item",
    )
    def delete(self, request, line_item_id, *args, **kwargs):
        from .models import LTILineItem

        try:
            line_item = LTILineItem.objects.get(id=line_item_id)
        except LTILineItem.DoesNotExist:
            return Response(
                {"error": "Line item not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Check permissions
        user = request.user
        if not user.is_superuser and not user.is_staff:
            if line_item.resource_link.course and line_item.resource_link.course.instructor != user:
                return Response(
                    {"error": "You don't have permission to delete this line item."},
                    status=status.HTTP_403_FORBIDDEN
                )

        line_item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class LTIGradeSubmissionListView(generics.ListAPIView):
    """
    Lists grade submissions for LTI line items.
    """
    permission_classes = [IsAuthenticated, IsInstructorOrAdmin]

    @extend_schema(
        tags=["LTI AGS"],
        description="List grade submissions for line items",
    )
    def get(self, request, *args, **kwargs):
        from .models import LTIGradeSubmission
        from .serializers import LTIGradeSubmissionListSerializer

        user = request.user
        tenant = getattr(request, "tenant", None)

        query = LTIGradeSubmission.objects.select_related(
            'line_item', 'line_item__resource_link', 'user'
        )

        if tenant:
            query = query.filter(line_item__resource_link__platform__tenant=tenant)

        # Non-admin users only see submissions for their courses
        if not user.is_superuser and not user.is_staff:
            query = query.filter(line_item__resource_link__course__instructor=user)

        # Filtering
        line_item_id = request.query_params.get('line_item_id')
        user_id = request.query_params.get('user_id')
        status_filter = request.query_params.get('status')

        if line_item_id:
            query = query.filter(line_item_id=line_item_id)
        if user_id:
            query = query.filter(user_id=user_id)
        if status_filter:
            query = query.filter(status=status_filter.upper())

        serializer = LTIGradeSubmissionListSerializer(
            query.order_by('-created_at')[:100], many=True
        )
        return Response(serializer.data)


class LTIGradeSubmissionDetailView(generics.RetrieveAPIView):
    """
    Retrieve details of a specific grade submission.
    """
    permission_classes = [IsAuthenticated, IsInstructorOrAdmin]

    @extend_schema(
        tags=["LTI AGS"],
        description="Get grade submission details",
    )
    def get(self, request, submission_id, *args, **kwargs):
        from .models import LTIGradeSubmission
        from .serializers import LTIGradeSubmissionSerializer

        try:
            submission = LTIGradeSubmission.objects.select_related(
                'line_item', 'user'
            ).get(id=submission_id)
        except LTIGradeSubmission.DoesNotExist:
            return Response(
                {"error": "Grade submission not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Check permissions
        user = request.user
        if not user.is_superuser and not user.is_staff:
            course = submission.line_item.resource_link.course
            if course and course.instructor != user:
                return Response(
                    {"error": "You don't have permission to view this submission."},
                    status=status.HTTP_403_FORBIDDEN
                )

        return Response(LTIGradeSubmissionSerializer(submission).data)


class LTISubmitGradeView(APIView):
    """
    Submit a grade to an LTI platform via AGS.
    Creates a grade submission record and attempts to send it to the platform.
    """
    permission_classes = [IsAuthenticated, IsInstructorOrAdmin]

    @extend_schema(
        tags=["LTI AGS"],
        description="Submit a grade to the LTI platform",
    )
    def post(self, request, *args, **kwargs):
        from .models import LTILineItem, LTIGradeSubmission
        from .serializers import LTIGradeSubmissionCreateSerializer, LTIGradeSubmissionSerializer
        from .services import AGSService, AGSServiceError

        serializer = LTIGradeSubmissionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        line_item = serializer.validated_data['line_item']
        target_user = serializer.validated_data['user']
        current_user = request.user

        # Check permissions
        if not current_user.is_superuser and not current_user.is_staff:
            course = line_item.resource_link.course
            if course and course.instructor != current_user:
                return Response(
                    {"error": "You don't have permission to submit grades for this line item."},
                    status=status.HTTP_403_FORBIDDEN
                )

        # Create the grade submission record
        grade_submission = serializer.save(status=LTIGradeSubmission.SubmissionStatus.PENDING)

        # Attempt to submit to the LTI platform using _post_score_to_platform directly
        # since submit_score creates its own record
        try:
            ags_service = AGSService(line_item.resource_link.platform)
            ags_service._post_score_to_platform(
                line_item=line_item,
                lti_user_id=grade_submission.lti_user_id,
                score=float(grade_submission.score),
                score_maximum=float(grade_submission.score_maximum),
                comment=grade_submission.comment,
                activity_progress=grade_submission.activity_progress,
                grading_progress=grade_submission.grading_progress,
            )

            # Update submission status on success
            grade_submission.status = LTIGradeSubmission.SubmissionStatus.SUBMITTED
            grade_submission.submitted_at = timezone.now()
            grade_submission.save()

            logger.info(
                f"Grade submitted successfully for user {target_user.id} "
                f"on line item {line_item.id}"
            )

        except AGSServiceError as e:
            # Mark as failed but keep the record for retry
            grade_submission.status = LTIGradeSubmission.SubmissionStatus.FAILED
            grade_submission.error_message = str(e)
            grade_submission.save()

            logger.error(f"Failed to submit grade to LTI platform: {e}")

            return Response(
                {
                    "message": "Grade recorded but submission to LTI platform failed. Will retry.",
                    "submission": LTIGradeSubmissionSerializer(grade_submission).data,
                    "error": str(e)
                },
                status=status.HTTP_202_ACCEPTED
            )

        return Response(
            LTIGradeSubmissionSerializer(grade_submission).data,
            status=status.HTTP_201_CREATED
        )


class LTIRetryFailedSubmissionsView(APIView):
    """
    Retry failed grade submissions to LTI platforms.
    """
    permission_classes = [IsAuthenticated, IsInstructorOrAdmin]

    @extend_schema(
        tags=["LTI AGS"],
        description="Retry failed grade submissions",
    )
    def post(self, request, *args, **kwargs):
        from .models import LTIGradeSubmission, LTILineItem
        from .serializers import RetryFailedSubmissionsSerializer
        from .services import AGSService, AGSServiceError

        serializer = RetryFailedSubmissionsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        line_item_id = serializer.validated_data.get('line_item_id')
        submission_ids = serializer.validated_data.get('submission_ids', [])
        max_retries = serializer.validated_data.get('max_retries', 3)

        user = request.user
        tenant = getattr(request, "tenant", None)

        # Build query for failed submissions
        query = LTIGradeSubmission.objects.filter(
            status=LTIGradeSubmission.SubmissionStatus.FAILED,
            retry_count__lt=max_retries
        ).select_related('line_item', 'line_item__resource_link__platform')

        if tenant:
            query = query.filter(line_item__resource_link__platform__tenant=tenant)

        if line_item_id:
            query = query.filter(line_item_id=line_item_id)

        if submission_ids:
            query = query.filter(id__in=submission_ids)

        # Check permissions for non-admin users
        if not user.is_superuser and not user.is_staff:
            query = query.filter(line_item__resource_link__course__instructor=user)

        failed_submissions = list(query)

        if not failed_submissions:
            return Response(
                {"message": "No failed submissions found to retry."},
                status=status.HTTP_200_OK
            )

        # Process retries
        results = {
            "total": len(failed_submissions),
            "success": 0,
            "failed": 0,
            "errors": []
        }

        for submission in failed_submissions:
            submission.status = LTIGradeSubmission.SubmissionStatus.RETRYING
            submission.retry_count += 1
            submission.save()

            try:
                ags_service = AGSService(submission.line_item.resource_link.platform)
                # Use _post_score_to_platform directly since we already have the submission record
                ags_service._post_score_to_platform(
                    line_item=submission.line_item,
                    lti_user_id=submission.lti_user_id,
                    score=float(submission.score),
                    score_maximum=float(submission.score_maximum),
                    comment=submission.comment,
                    activity_progress=submission.activity_progress,
                    grading_progress=submission.grading_progress,
                )

                submission.status = LTIGradeSubmission.SubmissionStatus.SUBMITTED
                submission.submitted_at = timezone.now()
                submission.error_message = ""
                submission.save()

                results["success"] += 1

            except AGSServiceError as e:
                submission.status = LTIGradeSubmission.SubmissionStatus.FAILED
                submission.error_message = str(e)
                submission.save()

                results["failed"] += 1
                results["errors"].append({
                    "submission_id": str(submission.id),
                    "error": str(e)
                })

        logger.info(
            f"Retry results: {results['success']} succeeded, {results['failed']} failed "
            f"out of {results['total']} submissions"
        )

        return Response(results)
