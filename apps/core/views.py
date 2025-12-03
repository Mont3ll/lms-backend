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
from rest_framework.permissions import IsAdminUser, IsAuthenticated # Django REST Framework's built-in

from apps.core.models import Tenant # Assuming Tenant is in core.models
from apps.users.models import User
from apps.courses.models import Course
from apps.analytics.models import Event, Report # Assuming Event and Report are in analytics.models
from apps.analytics.serializers import ReportSerializer
from apps.enrollments.models import Enrollment, LearnerProgress
from apps.assessments.models import Assessment, AssessmentAttempt
from .models import Tenant, TenantDomain
from .serializers import TenantSerializer, TenantDomainSerializer
from apps.users.permissions import IsAdminOrTenantAdmin, IsLearner, IsInstructorOrAdmin
from drf_spectacular.utils import extend_schema
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
    """
    permission_classes = [IsAdminUser] # Ensures only staff/superusers can access

    def get(self, request, format=None):
        try:
            total_tenants = Tenant.objects.count()
            total_users = User.objects.filter(is_active=True).count() # Count only active users
            total_courses = Course.objects.count() # Or filter by published status

            # Active users today (example: based on login events OR last_login field)
            today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
            # Using last_login is more efficient if updated regularly
            active_users_today = User.objects.filter(last_login__gte=today_start).count()
            # OR based on login events (can be slower on large event tables):
            # active_users_today = Event.objects.filter(
            #     event_type='USER_LOGIN',
            #     created_at__gte=today_start
            # ).values('user_id').distinct().count()

            # User growth (example: new users created per month for last 6 months)
            six_months_ago = timezone.now() - timedelta(days=6*30)
            user_growth_data = User.objects.filter(date_joined__gte=six_months_ago)\
                .annotate(month=TruncMonth('date_joined'))\
                .values('month')\
                .annotate(users=Count('id'))\
                .order_by('month')

            user_growth_formatted = [
                {"month": item['month'].strftime("%b %Y"), "users": item['users']}
                for item in user_growth_data
            ]

            # Recent System Events (example: last 5 significant events)
            # Define what constitutes a "system event" more clearly
            recent_system_events_qs = Event.objects.filter(
                # Example: Track tenant creation, superuser logins, major errors etc.
                Q(event_type='TENANT_CREATED') | # Assuming you have such an event type
                Q(event_type='ADMIN_LOGIN_SUCCESS', user__is_superuser=True) |
                Q(event_type='SYSTEM_ERROR_CRITICAL')
            ).select_related('user').order_by('-created_at')[:5]

            recent_events_formatted = [
                {
                    "id": str(event.id),
                    "type": event.event_type,
                    # Create a more descriptive message in the AnalyticsService.track_event context_data
                    "description": event.context_data.get('summary', f"Event type: {event.get_event_type_display()}"),
                    "user_email": event.user.email if event.user else "System",
                    "timestamp": event.created_at.isoformat()
                } for event in recent_system_events_qs
            ]

            stats = {
                "totalTenants": total_tenants,
                "totalUsers": total_users,
                "totalCourses": total_courses,
                "activeUsersToday": active_users_today,
                "userGrowth": user_growth_formatted,
                "recentSystemEvents": recent_events_formatted,
            }
            return Response(stats)

        except Exception as e:
            logger.error(f"Error generating admin dashboard stats: {e}", exc_info=True)
            return Response({"detail": "Could not retrieve dashboard statistics."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
            
            active_courses = enrollments.filter(status='ACTIVE').count()
            completed_courses = enrollments.filter(status='COMPLETED').count()
            
            # Certificates earned
            certificates_earned = 0
            try:
                from apps.enrollments.models import Certificate
                certificates_earned = Certificate.objects.filter(user=user, status='ISSUED').count()
            except ImportError:
                pass
            
            # Learning streak - consecutive days with learning activity
            learning_streak = self.calculate_learning_streak(user)
            
            # Overall Progress - Include both active and completed enrollments
            aggregation = enrollments.filter(status__in=['ACTIVE', 'COMPLETED']).aggregate(avg_progress=Avg('progress'))
            overall_progress = aggregation['avg_progress'] or 0

            # Total study hours - Based on completed content items (estimate)
            completed_content_count = LearnerProgress.objects.filter(enrollment__user=user, status='COMPLETED').count()
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
                activity_type = "Completed" if item.status == 'COMPLETED' else "Started"
                recent_activity.append({
                    "description": f"{activity_type} '{item.content_item.title}' in '{item.enrollment.course.title}'",
                    "timestamp": item.updated_at.strftime("%b %d, %Y at %I:%M %p")
                })

            # Upcoming Deadlines
            upcoming_deadlines_qs = Assessment.objects.filter(
                course__enrollments__user=user,
                course__enrollments__status__in=['ACTIVE'],
                due_date__gte=timezone.now().date(),
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
                status='COMPLETED'
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
                status__in=['SUBMITTED', 'GRADED'],
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
                status__in=['IN_PROGRESS', 'COMPLETED']
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
                status='COMPLETED',
                updated_at__date__gte=week_start
            ).count()
            
            # Weekly assessments taken
            weekly_assessments = AssessmentAttempt.objects.filter(
                user=user,
                start_time__date__gte=week_start,
                status__in=['SUBMITTED', 'GRADED']
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
                status='ISSUED'
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
        except Exception as e:
            logger.error(f"Error generating learner dashboard stats for user {user.id}: {e}", exc_info=True)
            return Response({"detail": "Could not retrieve dashboard statistics."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
            published_courses = instructor_courses.filter(status='PUBLISHED').count()
            draft_courses = instructor_courses.filter(status='DRAFT').count()
            
            # Total enrollments across all instructor's courses
            total_enrollments = Enrollment.objects.filter(course__instructor=user).count()
            active_enrollments = Enrollment.objects.filter(course__instructor=user, status='ACTIVE').count()
            
            # Active students count (distinct users enrolled in instructor's courses)
            active_students = User.objects.filter(
                enrollments__course__instructor=user,
                enrollments__status='ACTIVE'
            ).distinct().count()

            # Pending grading count
            pending_grading = 0
            try:
                pending_grading = AssessmentAttempt.objects.filter(
                    assessment__course__instructor=user,
                    status='SUBMITTED'
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
                        status='COMPLETED'
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
                upcoming_deadlines_qs = Assessment.objects.filter(
                    course__instructor=user,
                    due_date__gte=timezone.now().date()
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
                    completed = Enrollment.objects.filter(course=course, status='COMPLETED').count()
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

            # Top students by activity (simplified)
            top_students = []
            # For now, return empty list to avoid potential model issues

            # Revenue data (simplified for now)
            revenue_data = {
                "thisMonth": 0,
                "total": 0,
                "avgPerCourse": 0,
                "growth": 0
            }

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
                "contentProgress": content_progress
            }
            return Response(stats)
        except Exception as e:
            logger.error(f"Error generating instructor dashboard stats for user {user.id}: {e}", exc_info=True)
            return Response({"detail": "Could not retrieve dashboard statistics."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(tags=['Admin - Tenants'])
class TenantListView(generics.ListAPIView):
    """
    List all tenants (superuser only).
    Provides a simple list view for tenant selection in forms.
    """
    serializer_class = TenantSerializer
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    
    def get_queryset(self):
        if not self.request.user.is_superuser:
            return Tenant.objects.none()
        return Tenant.objects.filter(is_active=True).order_by('name')


@extend_schema(tags=['Admin - Tenants'])
class TenantStatsView(APIView):
    """
    Get overview statistics for all tenants (superuser only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    
    def get(self, request):
        if not request.user.is_superuser:
            return Response(
                {"detail": "You do not have permission to perform this action."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Import here to avoid circular imports
        from apps.users.models import User
        from apps.courses.models import Course
        from apps.enrollments.models import Enrollment
        
        thirty_days_ago = timezone.now() - timedelta(days=30)
        
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
                .order_by('-user_count')[:10]  # Top 10 by user count
            )
        }
        
        return Response(stats)


@extend_schema(tags=['Admin - Tenants'])
class TenantDomainListView(generics.ListAPIView):
    """
    List domains for a specific tenant (superuser only).
    """
    serializer_class = TenantDomainSerializer
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    
    def get_queryset(self):
        if not self.request.user.is_superuser:
            return TenantDomain.objects.none()
            
        tenant_id = self.kwargs.get('tenant_id')
        if tenant_id:
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
            serializer = ReportSerializer(reports, many=True)
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
