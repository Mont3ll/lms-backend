from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Count, Q, Avg, Sum, Max, Min
from django.utils import timezone
from datetime import datetime, timedelta
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth, TruncYear
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, OpenApiParameter

from .models import (
    CourseAnalytics, StudentEngagementMetric, InstructorAnalytics, 
    PredictiveAnalytics, AIInsights, RealTimeMetrics,
    LearningEfficiency, SocialLearningMetrics, Report, Dashboard, Event,
    StudentPerformance, EngagementMetrics, AssessmentAnalytics,
    LearningPathProgress, ContentInteraction, CourseCompletion,
    LearningObjectiveProgress, RevenueAnalytics, DeviceUsageAnalytics,
    GeographicAnalytics
)
from .serializers import (
    EventSerializer, CourseAnalyticsSerializer, StudentEngagementMetricSerializer,
    InstructorAnalyticsSerializer, PredictiveAnalyticsSerializer,
    AIInsightsSerializer, RealTimeMetricsSerializer, LearningEfficiencySerializer,
    SocialLearningMetricsSerializer, ReportSerializer, DashboardSerializer,
    StudentPerformanceSerializer, EngagementMetricsSerializer,
    AssessmentAnalyticsSerializer, LearningPathProgressSerializer,
    ContentInteractionSerializer, CourseCompletionSerializer,
    LearningObjectiveProgressSerializer, RevenueAnalyticsSerializer,
    DeviceUsageAnalyticsSerializer, GeographicAnalyticsSerializer,
    InstructorAnalyticsDashboardSerializer, PredictiveAnalyticsDataSerializer,
    AIInsightsDataSerializer, RealTimeDataSerializer, SocialLearningDataSerializer,
    LearningEfficiencyDataSerializer
)
from .services import AnalyticsService
from apps.courses.models import Course
from apps.users.models import User


@extend_schema(tags=['Analytics - Reports'])
class ReportDefinitionViewSet(viewsets.ViewSet):
    """
    ViewSet for managing analytics reports definitions and data generation.
    """
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        """List all available analytics reports."""
        reports = Report.objects.filter(tenant=request.user.tenant)
        serializer = ReportSerializer(reports, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """Get a specific report definition."""
        report = get_object_or_404(Report, pk=pk, tenant=request.user.tenant)
        serializer = ReportSerializer(report)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def generate(self, request, pk=None):
        """Generate report data for a specific report definition."""
        report = get_object_or_404(Report, pk=pk, tenant=request.user.tenant)
        
        # Get filters from request
        filters = request.data.get('filters', {})
        
        # Mock data structure for now
        data = {
            'report_id': report.id,
            'report_name': report.name,
            'generated_at': timezone.now(),
            'filters': filters,
            'data': []
        }
        
        return Response(data)


@extend_schema(tags=['Analytics - Dashboards'])
class DashboardDefinitionViewSet(viewsets.ViewSet):
    """
    ViewSet for managing analytics dashboards.
    """
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        """List all available dashboards."""
        dashboards = Dashboard.objects.filter(tenant=request.user.tenant)
        serializer = DashboardSerializer(dashboards, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """Get a specific dashboard definition."""
        dashboard = get_object_or_404(Dashboard, pk=pk, tenant=request.user.tenant)
        serializer = DashboardSerializer(dashboard)
        return Response(serializer.data)


@extend_schema(tags=['Analytics - Main'])
class InstructorAnalyticsView(APIView):
    """
    Main API view for instructor analytics dashboard.
    This serves the complete analytics data structure for the frontend.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(name='time_range', type=str, description='Time range filter'),
            OpenApiParameter(name='course_id', type=str, description='Course ID filter'),
        ]
    )
    def get(self, request):
        """Get comprehensive instructor analytics data."""
        user = request.user
        
        # Get filters
        time_range = request.query_params.get('time_range', '30d')
        course_id = request.query_params.get('course_id', 'all')
        
        # Calculate date range
        end_date = timezone.now().date()
        if time_range == '7d':
            start_date = end_date - timedelta(days=7)
        elif time_range == '30d':
            start_date = end_date - timedelta(days=30)
        elif time_range == '90d':
            start_date = end_date - timedelta(days=90)
        elif time_range == '1y':
            start_date = end_date - timedelta(days=365)
        else:
            start_date = end_date - timedelta(days=30)
        
        # Build analytics data
        analytics_data = self._build_analytics_data(user, start_date, end_date, course_id)
        
        return Response(analytics_data)

    def _build_analytics_data(self, user, start_date, end_date, course_id):
        """Build comprehensive analytics data structure."""
        
        # Get user's courses
        courses = Course.objects.filter(instructor=user)
        if course_id != 'all':
            courses = courses.filter(id=course_id)
        
        # Overview metrics
        overview = self._get_overview_metrics(user, courses, start_date, end_date)
        
        # Course performance
        course_performance = self._get_course_performance(courses, start_date, end_date)
        
        # Student engagement
        student_engagement = self._get_student_engagement(courses, start_date, end_date)
        
        # Revenue data
        revenue_data = self._get_revenue_data(courses, start_date, end_date)
        
        # Top performers
        top_performers = self._get_top_performers(courses, start_date, end_date)
        
        # Student distribution
        student_distribution = self._get_student_distribution(courses)
        
        # Cumulative progress
        cumulative_progress = self._get_cumulative_progress(courses, start_date, end_date)
        
        # Activity heatmap
        activity_heatmap = self._get_activity_heatmap(courses, start_date, end_date)
        
        # Device usage
        device_usage = self._get_device_usage(courses, start_date, end_date)
        
        # Geographic data
        geographic_data = self._get_geographic_data(courses, start_date, end_date)
        
        # Learning paths
        learning_paths = self._get_learning_paths(courses, start_date, end_date)
        
        # Predictive analytics
        predictive_analytics = self._get_predictive_analytics(courses, start_date, end_date)
        
        # AI insights
        ai_insights = self._get_ai_insights(courses, start_date, end_date)
        
        # Real-time data
        real_time_data = self._get_real_time_data(courses)
        
        # Social learning
        social_learning = self._get_social_learning(courses, start_date, end_date)
        
        # Learning efficiency
        learning_efficiency = self._get_learning_efficiency(courses, start_date, end_date)
        
        return {
            'overview': overview,
            'coursePerformance': course_performance,
            'studentEngagement': student_engagement,
            'revenueData': revenue_data,
            'topPerformers': top_performers,
            'studentDistribution': student_distribution,
            'cumulativeProgress': cumulative_progress,
            'activityHeatmap': activity_heatmap,
            'deviceUsage': device_usage,
            'geographicData': geographic_data,
            'learningPaths': learning_paths,
            'predictiveAnalytics': predictive_analytics,
            'aiInsights': ai_insights,
            'realTimeData': real_time_data,
            'socialLearning': social_learning,
            'learningEfficiency': learning_efficiency,
        }

    def _get_overview_metrics(self, user, courses, start_date, end_date):
        """Get overview metrics."""
        total_students = User.objects.filter(
            enrollments__course__in=courses,
            role=User.Role.LEARNER
        ).distinct().count()
        
        total_courses = courses.count()
        
        # Get revenue data
        revenue_analytics = RevenueAnalytics.objects.filter(
            course__in=courses,
            period_start__gte=start_date,
            period_end__lte=end_date
        ).aggregate(
            total_revenue=Sum('total_revenue')
        )
        
        total_revenue = revenue_analytics['total_revenue'] or 0
        
        # Get completion rate
        total_enrollments = User.objects.filter(
            enrollments__course__in=courses
        ).count()
        
        completed_courses = CourseCompletion.objects.filter(
            course__in=courses,
            completion_date__isnull=False
        ).count()
        
        completion_rate = (completed_courses / total_enrollments * 100) if total_enrollments > 0 else 0
        
        # Get average rating from CourseAnalytics
        course_ids = list(courses.values_list('id', flat=True))
        rating_data = CourseAnalytics.objects.filter(
            course_id__in=course_ids,
            date__gte=start_date,
            date__lte=end_date
        ).aggregate(
            avg_rating=Avg('avg_rating'),
            total_reviews=Sum('total_reviews')
        )
        avg_rating = float(rating_data['avg_rating']) if rating_data['avg_rating'] else 0
        
        # Get engagement rate from CourseAnalytics
        engagement_data = CourseAnalytics.objects.filter(
            course_id__in=course_ids,
            date__gte=start_date,
            date__lte=end_date
        ).aggregate(
            avg_engagement=Avg('avg_engagement_score')
        )
        engagement_rate = float(engagement_data['avg_engagement']) if engagement_data['avg_engagement'] else 0
        
        return {
            'totalStudents': total_students,
            'totalCourses': total_courses,
            'totalRevenue': float(total_revenue),
            'avgRating': round(avg_rating, 1),
            'completionRate': round(completion_rate, 1),
            'engagementRate': round(engagement_rate, 1),
        }

    def _get_course_performance(self, courses, start_date, end_date):
        """Get course performance data."""
        performance_data = []
        
        for course in courses:
            # Get students count
            students_count = User.objects.filter(
                enrollments__course=course,
                role=User.Role.LEARNER
            ).distinct().count()
            
            # Get completion rate
            enrollments = User.objects.filter(enrollments__course=course).count()
            completions = CourseCompletion.objects.filter(
                course=course,
                completion_date__isnull=False
            ).count()
            
            completion_rate = (completions / enrollments * 100) if enrollments > 0 else 0
            
            # Get revenue
            revenue = RevenueAnalytics.objects.filter(
                course=course,
                period_start__gte=start_date,
                period_end__lte=end_date
            ).aggregate(total=Sum('total_revenue'))['total'] or 0
            
            # Get rating and engagement from CourseAnalytics
            course_analytics = CourseAnalytics.objects.filter(
                course_id=course.id,
                date__gte=start_date,
                date__lte=end_date
            ).aggregate(
                avg_rating=Avg('avg_rating'),
                avg_engagement=Avg('avg_engagement_score')
            )
            rating = float(course_analytics['avg_rating']) if course_analytics['avg_rating'] else 0
            engagement = float(course_analytics['avg_engagement']) if course_analytics['avg_engagement'] else 0
            
            performance_data.append({
                'id': str(course.id),
                'title': course.title,
                'students': students_count,
                'completionRate': round(completion_rate, 1),
                'rating': round(rating, 1),
                'revenue': float(revenue),
                'engagement': round(engagement, 1),
            })
        
        return performance_data

    def _get_student_engagement(self, courses, start_date, end_date):
        """Get student engagement metrics."""
        # Daily engagement
        daily_engagement = []
        current_date = start_date
        
        while current_date <= end_date:
            # Get engagement metrics for this date
            engagement_data = EngagementMetrics.objects.filter(
                course__in=courses,
                date=current_date
            ).aggregate(
                active_students=Sum('active_users'),
                total_time=Sum('session_duration')
            )
            
            active_students = engagement_data['active_students'] or 0
            time_spent = engagement_data['total_time'] or timedelta(0)
            time_spent_hours = time_spent.total_seconds() / 3600 if time_spent else 0
            
            daily_engagement.append({
                'date': current_date.strftime('%Y-%m-%d'),
                'activeStudents': active_students,
                'timeSpent': round(time_spent_hours, 1),
            })
            
            current_date += timedelta(days=1)
        
        # Weekly and monthly aggregations
        weekly_engagement = self._aggregate_engagement_by_period(daily_engagement, 'week')
        monthly_engagement = self._aggregate_engagement_by_period(daily_engagement, 'month')
        
        return {
            'daily': daily_engagement,
            'weekly': weekly_engagement,
            'monthly': monthly_engagement,
        }

    def _get_revenue_data(self, courses, start_date, end_date):
        """Get revenue analytics data."""
        # Monthly revenue
        monthly_revenue = []
        
        # Get monthly revenue data
        revenue_by_month = RevenueAnalytics.objects.filter(
            course__in=courses,
            period_start__gte=start_date,
            period_end__lte=end_date
        ).annotate(
            month=TruncMonth('period_start')
        ).values('month').annotate(
            total_revenue=Sum('total_revenue'),
            total_students=Sum('enrolled_students')
        ).order_by('month')
        
        for item in revenue_by_month:
            monthly_revenue.append({
                'month': item['month'].strftime('%Y-%m'),
                'revenue': float(item['total_revenue']),
                'students': item['total_students'],
            })
        
        # Revenue by course
        revenue_by_course = []
        for course in courses:
            revenue = RevenueAnalytics.objects.filter(
                course=course,
                period_start__gte=start_date,
                period_end__lte=end_date
            ).aggregate(
                total_revenue=Sum('total_revenue'),
                total_students=Sum('enrolled_students')
            )
            
            if revenue['total_revenue']:
                revenue_by_course.append({
                    'courseTitle': course.title,
                    'revenue': float(revenue['total_revenue']),
                    'students': revenue['total_students'] or 0,
                })
        
        return {
            'monthly': monthly_revenue,
            'byCourse': revenue_by_course,
        }

    def _get_top_performers(self, courses, start_date, end_date):
        """Get top performing courses and students."""
        # Top courses by completion rate
        top_courses = []
        for course in courses:
            enrollments = User.objects.filter(enrollments__course=course).count()
            completions = CourseCompletion.objects.filter(
                course=course,
                completion_date__isnull=False
            ).count()
            
            completion_rate = (completions / enrollments * 100) if enrollments > 0 else 0
            
            top_courses.append({
                'title': course.title,
                'metric': 'Completion Rate',
                'value': round(completion_rate, 1),
            })
        
        # Sort by completion rate
        top_courses.sort(key=lambda x: x['value'], reverse=True)
        
        # Top students
        top_students = StudentPerformance.objects.filter(
            course__in=courses,
            created_at__gte=start_date,
            created_at__lte=end_date
        ).select_related('student', 'course').order_by('-score')[:10]
        
        top_students_data = []
        for performance in top_students:
            top_students_data.append({
                'name': performance.student.get_full_name(),
                'course': performance.course.title,
                'progress': float(performance.completion_rate),
                'timeSpent': performance.time_spent.total_seconds() / 3600 if performance.time_spent else 0,
            })
        
        return {
            'courses': top_courses[:5],
            'students': top_students_data,
        }

    def _get_student_distribution(self, courses):
        """Get student distribution data."""
        total_students = User.objects.filter(
            enrollments__course__in=courses,
            role=User.Role.LEARNER
        ).distinct().count()
        
        # Active students (those with recent activity)
        active_students = User.objects.filter(
            enrollments__course__in=courses,
            role=User.Role.LEARNER,
            last_login__gte=timezone.now() - timedelta(days=7)
        ).distinct().count()
        
        # Completed courses
        completed_students = CourseCompletion.objects.filter(
            course__in=courses,
            completion_date__isnull=False
        ).values('student').distinct().count()
        
        # Calculate inactive and dropped
        inactive_students = total_students - active_students
        dropped_students = max(0, total_students - completed_students - active_students)
        
        return [
            {'name': 'Active Students', 'value': active_students, 'color': '#0088FE'},
            {'name': 'Inactive Students', 'value': inactive_students, 'color': '#00C49F'},
            {'name': 'Completed Courses', 'value': completed_students, 'color': '#FFBB28'},
            {'name': 'Dropped Out', 'value': dropped_students, 'color': '#FF8042'},
        ]

    def _get_cumulative_progress(self, courses, start_date, end_date):
        """Get cumulative progress data."""
        progress_data = []
        
        # Generate monthly progress data
        current_date = start_date
        while current_date <= end_date:
            # Get progress for this month
            month_end = (current_date.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            
            completed = CourseCompletion.objects.filter(
                course__in=courses,
                completion_date__lte=month_end
            ).count()
            
            in_progress = StudentPerformance.objects.filter(
                course__in=courses,
                created_at__lte=month_end,
                completion_rate__lt=100
            ).count()
            
            not_started = User.objects.filter(
                enrollments__course__in=courses
            ).exclude(
                id__in=StudentPerformance.objects.filter(
                    course__in=courses,
                    created_at__lte=month_end
                ).values_list('student_id', flat=True)
            ).count()
            
            progress_data.append({
                'date': current_date.strftime('%Y-%m'),
                'completed': completed,
                'inProgress': in_progress,
                'notStarted': not_started,
            })
            
            # Move to next month
            current_date = (current_date.replace(day=28) + timedelta(days=4)).replace(day=1)
        
        return progress_data

    def _get_activity_heatmap(self, courses, start_date, end_date):
        """Generate activity heatmap data from real Event data."""
        from django.db.models.functions import ExtractHour, ExtractWeekDay
        
        heatmap_data = []
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        
        # Get course IDs for filtering events
        course_ids = list(courses.values_list('id', flat=True))
        
        # Query events grouped by weekday and hour
        # Note: ExtractWeekDay returns 1=Sunday, 2=Monday, ..., 7=Saturday in Django
        event_counts = Event.objects.filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            context_data__course_id__in=[str(cid) for cid in course_ids]
        ).annotate(
            weekday=ExtractWeekDay('created_at'),
            hour=ExtractHour('created_at')
        ).values('weekday', 'hour').annotate(
            count=Count('id')
        ).order_by('weekday', 'hour')
        
        # Build a lookup dict for quick access
        # Convert Django weekday (1=Sun, 2=Mon, ..., 7=Sat) to our index (0=Mon, ..., 6=Sun)
        activity_lookup = {}
        for item in event_counts:
            django_weekday = item['weekday']
            # Convert: 1(Sun)->6, 2(Mon)->0, 3(Tue)->1, 4(Wed)->2, 5(Thu)->3, 6(Fri)->4, 7(Sat)->5
            day_idx = (django_weekday - 2) % 7
            activity_lookup[(day_idx, item['hour'])] = item['count']
        
        # Find max count for normalization
        max_count = max(activity_lookup.values()) if activity_lookup else 1
        
        # Generate heatmap data for each day and hour
        for day_idx, day in enumerate(days):
            for hour in range(24):
                count = activity_lookup.get((day_idx, hour), 0)
                # Normalize intensity to 0-1 range
                intensity = count / max_count if max_count > 0 else 0
                
                heatmap_data.append({
                    'day': day,
                    'hour': hour,
                    'intensity': round(intensity, 2),
                    'count': count,  # Include raw count for reference
                })
        
        return heatmap_data

    def _get_device_usage(self, courses, start_date, end_date):
        """Get device usage analytics."""
        device_usage = DeviceUsageAnalytics.objects.filter(
            tenant=courses.first().instructor.tenant if courses.exists() else None,
            date__gte=start_date,
            date__lte=end_date
        ).aggregate(
            total_desktop=Sum('desktop_users'),
            total_mobile=Sum('mobile_users'),
            total_tablet=Sum('tablet_users')
        )
        
        desktop_users = device_usage['total_desktop'] or 0
        mobile_users = device_usage['total_mobile'] or 0
        tablet_users = device_usage['total_tablet'] or 0
        
        total_users = desktop_users + mobile_users + tablet_users
        
        if total_users == 0:
            # Fallback to Event model device_type data
            course_ids = list(courses.values_list('id', flat=True))
            event_device_counts = Event.objects.filter(
                created_at__date__gte=start_date,
                created_at__date__lte=end_date,
                device_type__isnull=False
            ).filter(
                Q(context_data__course_id__in=[str(cid) for cid in course_ids]) |
                Q(tenant=courses.first().instructor.tenant if courses.exists() else None)
            ).values('device_type').annotate(
                count=Count('id')
            )
            
            device_lookup = {item['device_type'].lower(): item['count'] for item in event_device_counts}
            desktop_users = device_lookup.get('desktop', 0)
            mobile_users = device_lookup.get('mobile', 0)
            tablet_users = device_lookup.get('tablet', 0)
            total_users = desktop_users + mobile_users + tablet_users
        
        if total_users == 0:
            # Return empty data if still no real data (no mock)
            return [
                {'device': 'Desktop', 'percentage': 0, 'users': 0},
                {'device': 'Mobile', 'percentage': 0, 'users': 0},
                {'device': 'Tablet', 'percentage': 0, 'users': 0},
            ]
        
        return [
            {
                'device': 'Desktop',
                'percentage': round(desktop_users / total_users * 100, 1),
                'users': desktop_users,
            },
            {
                'device': 'Mobile',
                'percentage': round(mobile_users / total_users * 100, 1),
                'users': mobile_users,
            },
            {
                'device': 'Tablet',
                'percentage': round(tablet_users / total_users * 100, 1),
                'users': tablet_users,
            },
        ]

    def _get_geographic_data(self, courses, start_date, end_date):
        """Get geographic distribution data."""
        geo_data = GeographicAnalytics.objects.filter(
            tenant=courses.first().instructor.tenant if courses.exists() else None
        ).values('region').annotate(
            students=Sum('total_students'),
            revenue=Sum('total_revenue')
        )
        
        geographic_data = []
        for item in geo_data:
            geographic_data.append({
                'region': item['region'],
                'students': item['students'],
                'revenue': float(item['revenue']),
            })
        
        if not geographic_data:
            # Fallback: Try to get geographic data from Event model
            course_ids = list(courses.values_list('id', flat=True))
            event_geo_data = Event.objects.filter(
                created_at__date__gte=start_date,
                created_at__date__lte=end_date,
                country__isnull=False
            ).filter(
                Q(context_data__course_id__in=[str(cid) for cid in course_ids]) |
                Q(tenant=courses.first().instructor.tenant if courses.exists() else None)
            ).values('region').annotate(
                students=Count('user_id', distinct=True)
            ).order_by('-students')
            
            for item in event_geo_data:
                if item['region']:
                    geographic_data.append({
                        'region': item['region'],
                        'students': item['students'],
                        'revenue': 0,  # Revenue not available from events
                    })
        
        # Return empty array if still no data (no mock)
        return geographic_data

    def _get_learning_paths(self, courses, start_date, end_date):
        """Get learning path analytics from real data."""
        from apps.learning_paths.models import LearningPath
        
        # Get learning paths that include any of the instructor's courses
        course_ids = list(courses.values_list('id', flat=True))
        
        # Query learning path progress data
        learning_path_data = LearningPathProgress.objects.filter(
            learning_path__courses__in=course_ids,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).values('learning_path__title').annotate(
            completion_rate=Avg('completion_percentage'),
            avg_time_hours=Avg('actual_time_spent')
        ).order_by('-completion_rate')
        
        result = []
        for item in learning_path_data:
            # Convert timedelta to hours if present
            avg_time = 0
            if item['avg_time_hours']:
                avg_time = item['avg_time_hours'].total_seconds() / 3600
            
            result.append({
                'path': item['learning_path__title'],
                'completionRate': round(float(item['completion_rate'] or 0), 1),
                'avgTime': round(avg_time, 1),
            })
        
        # Return empty array if no data (no mock)
        return result

    def _get_predictive_analytics(self, courses, start_date, end_date):
        """Get predictive analytics data from real data sources."""
        # Students at risk
        students_at_risk = StudentPerformance.objects.filter(
            course__in=courses,
            risk_score__gte=60
        ).select_related('student').order_by('-risk_score')[:10]
        
        student_at_risk_data = []
        for performance in students_at_risk:
            student_at_risk_data.append({
                'id': str(performance.student.id),
                'name': performance.student.get_full_name(),
                'riskScore': float(performance.risk_score),
                'reasons': performance.risk_factors,
            })
        
        # Get predictive analytics from PredictiveAnalytics model
        tenant = courses.first().instructor.tenant if courses.exists() else None
        instructor_id = courses.first().instructor.id if courses.exists() else None
        
        predictive_data = PredictiveAnalytics.objects.filter(
            tenant=tenant,
            instructor_id=instructor_id,
            prediction_date__gte=start_date,
            prediction_date__lte=end_date
        ).order_by('-prediction_date').first()
        
        # Extract stored predictions or return empty
        course_recommendations = []
        revenue_forecasting = []
        trends_analysis = []
        
        if predictive_data:
            course_recommendations = predictive_data.course_recommendations or []
            revenue_forecasting = predictive_data.revenue_forecast or []
            trends_analysis = predictive_data.trends_analysis or []
        
        return {
            'studentAtRisk': student_at_risk_data,
            'courseRecommendations': course_recommendations,
            'revenueForecasting': revenue_forecasting,
            'trendsAnalysis': trends_analysis,
        }

    def _get_ai_insights(self, courses, start_date, end_date):
        """Get AI insights data from AIInsights model."""
        tenant = courses.first().instructor.tenant if courses.exists() else None
        instructor_id = courses.first().instructor.id if courses.exists() else None
        
        # Get the latest AI insights
        ai_insights = AIInsights.objects.filter(
            tenant=tenant,
            instructor_id=instructor_id,
            date__gte=start_date,
            date__lte=end_date
        ).order_by('-date').first()
        
        if ai_insights:
            return {
                'keyInsights': ai_insights.key_insights or [],
                'recommendations': ai_insights.recommendations or [],
                'anomalies': ai_insights.anomalies or [],
            }
        
        # Return empty structure if no AI insights available
        return {
            'keyInsights': [],
            'recommendations': [],
            'anomalies': [],
        }

    def _get_real_time_data(self, courses):
        """Get real-time analytics data from RealTimeMetrics model."""
        tenant = courses.first().instructor.tenant if courses.exists() else None
        instructor_id = courses.first().instructor.id if courses.exists() else None
        
        # Get the most recent real-time metrics
        realtime_metrics = RealTimeMetrics.objects.filter(
            tenant=tenant,
            instructor_id=instructor_id
        ).order_by('-timestamp').first()
        
        if realtime_metrics:
            return {
                'activeUsers': realtime_metrics.active_users,
                'currentSessions': realtime_metrics.current_sessions,
                'liveEngagement': float(realtime_metrics.live_engagement_rate),
                'serverHealth': float(realtime_metrics.server_health),
            }
        
        # Return zeros if no real-time data available
        return {
            'activeUsers': 0,
            'currentSessions': 0,
            'liveEngagement': 0,
            'serverHealth': 0,
        }

    def _get_social_learning(self, courses, start_date, end_date):
        """Get social learning metrics from real data."""
        from .models import DiscussionInteraction, PeerReview, CollaborativeProject
        
        course_ids = list(courses.values_list('id', flat=True))
        
        # Get discussion data from SocialLearningMetrics or DiscussionInteraction
        discussions_data = SocialLearningMetrics.objects.filter(
            course_id__in=course_ids,
            date__gte=start_date,
            date__lte=end_date
        ).values('course_id').annotate(
            messages=Sum('discussion_messages'),
            participants=Sum('discussion_participants')
        )
        
        discussions = []
        for item in discussions_data:
            discussions.append({
                'courseId': str(item['course_id']),
                'messages': item['messages'] or 0,
                'participants': item['participants'] or 0,
            })
        
        # Get peer review data
        peer_reviews_data = PeerReview.objects.filter(
            course__in=courses,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            status='submitted'
        ).values('course_id').annotate(
            reviews=Count('id'),
            avg_rating=Avg('rating')
        )
        
        peer_reviews = []
        for item in peer_reviews_data:
            peer_reviews.append({
                'courseId': str(item['course_id']),
                'reviews': item['reviews'] or 0,
                'avgRating': round(float(item['avg_rating'] or 0), 1),
            })
        
        # Get collaborative projects data
        projects_data = CollaborativeProject.objects.filter(
            course__in=courses,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).values('id', 'title').annotate(
            participant_count=Count('participants'),
            completion=Avg('completion_rate')
        )
        
        collaborative_projects = []
        for item in projects_data:
            collaborative_projects.append({
                'projectId': str(item['id']),
                'title': item['title'],
                'participants': item['participant_count'] or 0,
                'completionRate': round(float(item['completion'] or 0), 1),
            })
        
        return {
            'discussions': discussions,
            'peerReviews': peer_reviews,
            'collaborativeProjects': collaborative_projects,
        }

    def _get_learning_efficiency(self, courses, start_date, end_date):
        """Get learning efficiency data from LearningEfficiency model."""
        tenant = courses.first().instructor.tenant if courses.exists() else None
        instructor_id = courses.first().instructor.id if courses.exists() else None
        course_ids = list(courses.values_list('id', flat=True))
        
        # Get the latest learning efficiency data
        efficiency_data = LearningEfficiency.objects.filter(
            tenant=tenant,
            instructor_id=instructor_id,
            date__gte=start_date,
            date__lte=end_date
        ).filter(
            Q(course_id__in=course_ids) | Q(course_id__isnull=True)
        ).order_by('-date').first()
        
        if efficiency_data:
            return {
                'optimalStudyTimes': efficiency_data.optimal_study_times or [],
                'contentEffectiveness': efficiency_data.content_effectiveness or [],
                'difficultyProgression': efficiency_data.difficulty_progression or [],
            }
        
        # Return empty structure if no data
        return {
            'optimalStudyTimes': [],
            'contentEffectiveness': [],
            'difficultyProgression': [],
        }

    def _aggregate_engagement_by_period(self, daily_data, period):
        """Aggregate daily engagement data by week or month."""
        # This is a simplified aggregation - in a real implementation,
        # you'd properly group by week/month
        return daily_data[:10]  # Return first 10 items as mock


@extend_schema(tags=['Analytics - Student Performance'])
class StudentPerformanceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for student performance analytics.
    """
    serializer_class = StudentPerformanceSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.role == User.Role.INSTRUCTOR:
            return StudentPerformance.objects.filter(course__instructor=user)
        elif user.role == User.Role.LEARNER:
            return StudentPerformance.objects.filter(student=user)
        return StudentPerformance.objects.none()


@extend_schema(tags=['Analytics - Engagement'])
class EngagementMetricsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for engagement metrics.
    """
    serializer_class = EngagementMetricsSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_instructor:
            return EngagementMetrics.objects.filter(course__instructor=user)
        return EngagementMetrics.objects.none()


@extend_schema(tags=['Analytics - Assessments'])
class AssessmentAnalyticsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for assessment analytics.
    """
    serializer_class = AssessmentAnalyticsSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_instructor:
            return AssessmentAnalytics.objects.filter(assessment__course__instructor=user)
        return AssessmentAnalytics.objects.none()


@extend_schema(tags=['Analytics - Tracking'])
class AnalyticsTrackingView(APIView):
    """
    API view for tracking analytics events.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        """Track an analytics event."""
        serializer = EventSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(
                user=request.user,
                tenant=request.user.tenant,
                ip_address=request.META.get('REMOTE_ADDR')
            )
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
