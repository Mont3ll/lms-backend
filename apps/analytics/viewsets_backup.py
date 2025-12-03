from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Count, Q, Avg, Sum
from django.utils import timezone
from datetime import datetime, timedelta
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth
from django.shortcuts import get_object_or_404

from .models import (
    CourseAnalytics, StudentEngagementMetric, InstructorAnalytics, 
    PredictiveAnalytics, AIInsights, RealTimeMetrics,
    LearningEfficiency, SocialLearningMetrics, Report, Dashboard, Event
)
from .serializers import (
    EventSerializer, CourseAnalyticsSerializer, StudentEngagementMetricSerializer,
    InstructorAnalyticsSerializer, PredictiveAnalyticsSerializer,
    AIInsightsSerializer, RealTimeMetricsSerializer, LearningEfficiencySerializer,
    SocialLearningMetricsSerializer, ReportSerializer, DashboardSerializer
)
from .services import AnalyticsService
from apps.courses.models import Course
from apps.users.models import User
from drf_spectacular.utils import extend_schema


@extend_schema(tags=['Analytics'])
class ReportDefinitionViewSet(viewsets.ViewSet):
    """
    API endpoint for managing report definitions (Admin only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    
    def list(self, request):
        """List available report definitions."""
        # Mock report definitions until actual implementation
        report_definitions = [
            {
                'id': 'user-engagement',
                'name': 'User Engagement Report',
                'description': 'Track user activity and engagement metrics',
                'parameters': ['date_range', 'tenant_id'],
                'output_format': ['pdf', 'excel', 'csv']
            },
            {
                'id': 'course-completion',
                'name': 'Course Completion Report',
                'description': 'Analysis of course completion rates',
                'parameters': ['course_id', 'date_range'],
                'output_format': ['pdf', 'excel', 'csv']
            },
            {
                'id': 'assessment-performance',
                'name': 'Assessment Performance Report',
                'description': 'Student performance on assessments',
                'parameters': ['assessment_id', 'date_range'],
                'output_format': ['pdf', 'excel', 'csv']
            }
        ]
        return Response(report_definitions)


@extend_schema(tags=['Analytics'])
class DashboardDefinitionViewSet(viewsets.ViewSet):
    """
    API endpoint for managing dashboard definitions (Admin only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    
    def list(self, request):
        """List available dashboard definitions."""
        # Mock dashboard definitions until actual implementation
        dashboard_definitions = [
            {
                'id': 'admin-overview',
                'name': 'Admin Overview Dashboard',
                'description': 'High-level metrics for administrators',
                'widgets': ['user_count', 'course_count', 'enrollment_trends', 'activity_feed']
            },
            {
                'id': 'instructor-insights',
                'name': 'Instructor Insights Dashboard',
                'description': 'Course-specific metrics for instructors',
                'widgets': ['course_enrollment', 'student_progress', 'assessment_scores', 'discussion_activity']
            },
            {
                'id': 'learner-progress',
                'name': 'Learner Progress Dashboard',
                'description': 'Personal learning analytics for students',
                'widgets': ['progress_overview', 'upcoming_deadlines', 'achievements', 'recommendations']
            }
        ]
        return Response(dashboard_definitions)


@extend_schema(tags=['Analytics'])
class ReportDataView(APIView):
    """
    API endpoint for fetching report data.
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, report_slug):
        """Get data for a specific report."""
        # Mock report data until actual implementation
        from apps.users.models import User
        from apps.courses.models import Course
        from apps.enrollments.models import Enrollment
        
        thirty_days_ago = timezone.now() - timedelta(days=30)
        
        if report_slug == 'user-engagement':
            data = {
                'total_users': User.objects.count(),
                'active_users_30d': User.objects.filter(last_login__gte=thirty_days_ago).count(),
                'new_users_30d': User.objects.filter(date_joined__gte=thirty_days_ago).count(),
                'engagement_trend': [
                    {'date': '2024-01-01', 'active_users': 45},
                    {'date': '2024-01-02', 'active_users': 52},
                    {'date': '2024-01-03', 'active_users': 48},
                    # Add more mock data points
                ]
            }
        elif report_slug == 'course-completion':
            data = {
                'total_courses': Course.objects.count(),
                'total_enrollments': Enrollment.objects.count(),
                'completion_rate': 0.75,
                'completion_by_course': [
                    {'course_title': 'Introduction to Python', 'completion_rate': 0.85},
                    {'course_title': 'Web Development Basics', 'completion_rate': 0.72},
                    {'course_title': 'Data Science Fundamentals', 'completion_rate': 0.68},
                ]
            }
        elif report_slug == 'assessment-performance':
            data = {
                'total_assessments': 0,  # Will be updated when assessment models are available
                'average_score': 0.78,
                'performance_by_assessment': [
                    {'assessment_title': 'Python Basics Quiz', 'average_score': 0.82},
                    {'assessment_title': 'HTML/CSS Test', 'average_score': 0.76},
                    {'assessment_title': 'Database Design Quiz', 'average_score': 0.71},
                ]
            }
        else:
            return Response(
                {'detail': 'Report not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        return Response(data)


@extend_schema(tags=['Analytics'])
class AnalyticsTrackingView(APIView):
    """
    API endpoint for tracking analytics events.
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        """Track an analytics event."""
        event_type = request.data.get('event_type')
        context_data = request.data.get('context_data', {})
        
        if not event_type:
            return Response(
                {'detail': 'event_type is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Here you would typically save to an Event model or send to an analytics service
        # For now, just log it
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Analytics event tracked: {event_type} by user {request.user.id}")
        
        return Response({'status': 'tracked'}, status=status.HTTP_201_CREATED)


class CourseAnalyticsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for course analytics data
    """
    serializer_class = CourseAnalyticsSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_instructor:
            return CourseAnalytics.objects.filter(course__instructor=user)
        return CourseAnalytics.objects.none()
    
    @action(detail=True, methods=['get'])
    def detailed_metrics(self, request, pk=None):
        """Get detailed metrics for a specific course"""
        course_analytics = self.get_object()
        service = AnalyticsService()
        
        detailed_data = service.get_detailed_course_metrics(course_analytics.course)
        return Response(detailed_data)
    
    @action(detail=True, methods=['get'])
    def engagement_trends(self, request, pk=None):
        """Get engagement trends over time"""
        course_analytics = self.get_object()
        
        # Get engagement data for the last 30 days
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=30)
        
        engagement_data = EngagementMetrics.objects.filter(
            course=course_analytics.course,
            date__range=[start_date, end_date]
        ).values('date').annotate(
            total_time=Sum('time_spent'),
            avg_score=Avg('average_score'),
            total_interactions=Sum('interactions_count')
        ).order_by('date')
        
        return Response(list(engagement_data))
    
    @action(detail=True, methods=['get'])
    def student_performance_overview(self, request, pk=None):
        """Get student performance overview for the course"""
        course_analytics = self.get_object()
        
        performance_data = StudentPerformance.objects.filter(
            course=course_analytics.course
        ).aggregate(
            avg_score=Avg('average_score'),
            total_submissions=Sum('total_submissions'),
            avg_time_spent=Avg('time_spent'),
            completion_rate=Avg('completion_percentage')
        )
        
        # Get score distribution
        score_ranges = [
            (0, 50, 'Below Average'),
            (50, 70, 'Average'),
            (70, 85, 'Good'),
            (85, 100, 'Excellent')
        ]
        
        distribution = []
        for min_score, max_score, label in score_ranges:
            count = StudentPerformance.objects.filter(
                course=course_analytics.course,
                average_score__gte=min_score,
                average_score__lt=max_score
            ).count()
            distribution.append({
                'range': f'{min_score}-{max_score}',
                'label': label,
                'count': count
            })
        
        return Response({
            'overview': performance_data,
            'score_distribution': distribution
        })


class StudentPerformanceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for student performance analytics
    """
    serializer_class = StudentPerformanceSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_instructor:
            return StudentPerformance.objects.filter(course__instructor=user)
        elif user.is_student:
            return StudentPerformance.objects.filter(student=user)
        return StudentPerformance.objects.none()
    
    @action(detail=False, methods=['get'])
    def by_course(self, request):
        """Get student performance grouped by course"""
        course_id = request.query_params.get('course_id')
        if not course_id:
            return Response({'error': 'course_id parameter is required'}, 
                          status=status.HTTP_400_BAD_REQUEST)
        
        course = get_object_or_404(Course, id=course_id)
        
        # Check permission
        if request.user.is_instructor and course.instructor != request.user:
            return Response({'error': 'Permission denied'}, 
                          status=status.HTTP_403_FORBIDDEN)
        
        performance_data = StudentPerformance.objects.filter(
            course=course
        ).select_related('student').order_by('-average_score')
        
        serializer = self.get_serializer(performance_data, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def struggling_students(self, request):
        """Get list of students who need attention"""
        course_id = request.query_params.get('course_id')
        threshold = float(request.query_params.get('threshold', 60))
        
        filters = Q(average_score__lt=threshold) | Q(completion_percentage__lt=50)
        
        if course_id:
            filters &= Q(course_id=course_id)
        
        if request.user.is_instructor:
            filters &= Q(course__instructor=request.user)
        
        struggling = StudentPerformance.objects.filter(filters).select_related(
            'student', 'course'
        ).order_by('average_score')
        
        serializer = self.get_serializer(struggling, many=True)
        return Response(serializer.data)


class EngagementMetricsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for engagement metrics
    """
    serializer_class = EngagementMetricsSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_instructor:
            return EngagementMetrics.objects.filter(course__instructor=user)
        return EngagementMetrics.objects.none()
    
    @action(detail=False, methods=['get'])
    def daily_engagement(self, request):
        """Get daily engagement metrics"""
        course_id = request.query_params.get('course_id')
        days = int(request.query_params.get('days', 30))
        
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days)
        
        filters = Q(date__range=[start_date, end_date])
        if course_id:
            filters &= Q(course_id=course_id)
        
        if request.user.is_instructor:
            filters &= Q(course__instructor=request.user)
        
        daily_data = EngagementMetrics.objects.filter(filters).values(
            'date'
        ).annotate(
            total_time=Sum('time_spent'),
            avg_score=Avg('average_score'),
            total_interactions=Sum('interactions_count'),
            unique_students=Count('student', distinct=True)
        ).order_by('date')
        
        return Response(list(daily_data))
    
    @action(detail=False, methods=['get'])
    def weekly_trends(self, request):
        """Get weekly engagement trends"""
        course_id = request.query_params.get('course_id')
        weeks = int(request.query_params.get('weeks', 12))
        
        end_date = timezone.now().date()
        start_date = end_date - timedelta(weeks=weeks)
        
        filters = Q(date__range=[start_date, end_date])
        if course_id:
            filters &= Q(course_id=course_id)
        
        if request.user.is_instructor:
            filters &= Q(course__instructor=request.user)
        
        weekly_data = EngagementMetrics.objects.filter(filters).annotate(
            week=TruncWeek('date')
        ).values('week').annotate(
            total_time=Sum('time_spent'),
            avg_score=Avg('average_score'),
            total_interactions=Sum('interactions_count'),
            unique_students=Count('student', distinct=True)
        ).order_by('week')
        
        return Response(list(weekly_data))


class AssessmentAnalyticsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for assessment analytics
    """
    serializer_class = AssessmentAnalyticsSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_instructor:
            return AssessmentAnalytics.objects.filter(assessment__course__instructor=user)
        return AssessmentAnalytics.objects.none()
    
    @action(detail=True, methods=['get'])
    def question_analysis(self, request, pk=None):
        """Get detailed question analysis for an assessment"""
        assessment_analytics = self.get_object()
        
        # This would need to be implemented based on your assessment structure
        # For now, return basic statistics
        question_stats = {
            'total_questions': assessment_analytics.total_questions,
            'average_score': assessment_analytics.average_score,
            'difficulty_distribution': assessment_analytics.difficulty_distribution,
            'completion_rate': assessment_analytics.completion_rate
        }
        
        return Response(question_stats)
    
    @action(detail=False, methods=['get'])
    def course_assessments(self, request):
        """Get all assessments for a course with analytics"""
        course_id = request.query_params.get('course_id')
        if not course_id:
            return Response({'error': 'course_id parameter is required'}, 
                          status=status.HTTP_400_BAD_REQUEST)
        
        course = get_object_or_404(Course, id=course_id)
        
        if request.user.is_instructor and course.instructor != request.user:
            return Response({'error': 'Permission denied'}, 
                          status=status.HTTP_403_FORBIDDEN)
        
        assessments = AssessmentAnalytics.objects.filter(
            assessment__course=course
        ).select_related('assessment')
        
        serializer = self.get_serializer(assessments, many=True)
        return Response(serializer.data)


class AnalyticsDashboardView(APIView):
    """
    Main analytics dashboard view that aggregates data from multiple sources
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """Get dashboard data for instructor or student"""
        user = request.user
        course_id = request.query_params.get('course_id')
        
        if user.is_instructor:
            return self.get_instructor_dashboard(user, course_id)
        elif user.is_student:
            return self.get_student_dashboard(user, course_id)
        else:
            return Response({'error': 'Invalid user type'}, 
                          status=status.HTTP_403_FORBIDDEN)
    
    def get_instructor_dashboard(self, user, course_id=None):
        """Get instructor dashboard data"""
        service = AnalyticsService()
        
        if course_id:
            course = get_object_or_404(Course, id=course_id, instructor=user)
            courses = [course]
        else:
            courses = Course.objects.filter(instructor=user)
        
        dashboard_data = {
            'overview': {
                'total_courses': len(courses),
                'total_students': sum(course.enrolled_students.count() for course in courses),
                'total_assessments': sum(course.assessments.count() for course in courses),
                'average_completion_rate': 0  # Will be calculated
            },
            'recent_activity': [],
            'course_analytics': [],
            'student_performance': {
                'struggling_students': [],
                'top_performers': []
            },
            'engagement_metrics': {
                'daily_engagement': [],
                'weekly_trends': []
            }
        }
        
        # Get detailed data for each course
        for course in courses:
            course_data = service.get_detailed_course_metrics(course)
            dashboard_data['course_analytics'].append(course_data)
        
        # Get struggling and top performing students
        if course_id:
            struggling = StudentPerformance.objects.filter(
                course_id=course_id,
                average_score__lt=60
            ).select_related('student')[:5]
            
            top_performers = StudentPerformance.objects.filter(
                course_id=course_id,
                average_score__gte=85
            ).select_related('student').order_by('-average_score')[:5]
        else:
            struggling = StudentPerformance.objects.filter(
                course__instructor=user,
                average_score__lt=60
            ).select_related('student', 'course')[:5]
            
            top_performers = StudentPerformance.objects.filter(
                course__instructor=user,
                average_score__gte=85
            ).select_related('student', 'course').order_by('-average_score')[:5]
        
        dashboard_data['student_performance']['struggling_students'] = [
            {
                'student_name': perf.student.get_full_name(),
                'course_name': perf.course.title,
                'average_score': perf.average_score,
                'completion_percentage': perf.completion_percentage
            }
            for perf in struggling
        ]
        
        dashboard_data['student_performance']['top_performers'] = [
            {
                'student_name': perf.student.get_full_name(),
                'course_name': perf.course.title,
                'average_score': perf.average_score,
                'completion_percentage': perf.completion_percentage
            }
            for perf in top_performers
        ]
        
        return Response(dashboard_data)
    
    def get_student_dashboard(self, user, course_id=None):
        """Get student dashboard data"""
        if course_id:
            courses = Course.objects.filter(id=course_id, enrolled_students=user)
        else:
            courses = user.enrolled_courses.all()
        
        dashboard_data = {
            'overview': {
                'total_courses': courses.count(),
                'completed_courses': 0,
                'in_progress_courses': 0,
                'average_score': 0
            },
            'course_progress': [],
            'recent_activity': [],
            'performance_metrics': {
                'strengths': [],
                'areas_for_improvement': []
            }
        }
        
        # Get performance data for each course
        for course in courses:
            try:
                performance = StudentPerformance.objects.get(
                    student=user, course=course
                )
                dashboard_data['course_progress'].append({
                    'course_name': course.title,
                    'completion_percentage': performance.completion_percentage,
                    'average_score': performance.average_score,
                    'time_spent': performance.time_spent,
                    'last_activity': performance.last_activity
                })
            except StudentPerformance.DoesNotExist:
                dashboard_data['course_progress'].append({
                    'course_name': course.title,
                    'completion_percentage': 0,
                    'average_score': 0,
                    'time_spent': 0,
                    'last_activity': None
                })
        
        return Response(dashboard_data)
