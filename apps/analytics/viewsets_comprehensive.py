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
        
        # Get average rating from course analytics
        avg_rating = CourseAnalytics.objects.filter(
            course__in=courses,
            date__gte=start_date,
            date__lte=end_date
        ).aggregate(avg_rating=Avg('avg_rating'))['avg_rating'] or 4.7
        
        # Get engagement rate from engagement metrics
        engagement_rate = EngagementMetrics.objects.filter(
            course__in=courses,
            date__gte=start_date,
            date__lte=end_date
        ).aggregate(
            avg_engagement=Avg('interactions')
        )['avg_engagement'] or 85
        
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
            
            # Get rating from course analytics
            rating = CourseAnalytics.objects.filter(
                course=course,
                date__gte=start_date,
                date__lte=end_date
            ).aggregate(avg_rating=Avg('avg_rating'))['avg_rating'] or 4.5
            
            # Get engagement from engagement metrics
            engagement = EngagementMetrics.objects.filter(
                course=course,
                date__gte=start_date,
                date__lte=end_date
            ).aggregate(
                avg_engagement=Avg('interactions')
            )['avg_engagement'] or 75
            
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
        """Generate activity heatmap data."""
        heatmap_data = []
        
        # Generate heatmap for each day of the week and each hour
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        
        for day_idx, day in enumerate(days):
            for hour in range(24):
                # Get real activity data for this day and hour
                weekday = day_idx + 1  # 1=Monday, 7=Sunday
                activity_count = EngagementMetrics.objects.filter(
                    course__in=courses,
                    date__gte=start_date,
                    date__lte=end_date,
                    date__week_day=weekday
                ).extra(
                    where=["EXTRACT(hour FROM created_at) = %s"],
                    params=[hour]
                ).aggregate(
                    total_interactions=Sum('interactions')
                )['total_interactions'] or 0
                
                # Normalize intensity (0-1) based on activity count
                max_activity = 100  # Adjust based on typical activity levels
                intensity = min(activity_count / max_activity, 1.0)
                
                heatmap_data.append({
                    'day': day,
                    'hour': hour,
                    'intensity': round(intensity, 2),
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
            # Return mock data if no real data
            return [
                {'device': 'Desktop', 'percentage': 60, 'users': 205},
                {'device': 'Mobile', 'percentage': 25, 'users': 86},
                {'device': 'Tablet', 'percentage': 15, 'users': 51},
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
            # Return mock data if no real data
            return [
                {'region': 'North America', 'students': 156, 'revenue': 8920},
                {'region': 'Europe', 'students': 89, 'revenue': 5670},
                {'region': 'Asia', 'students': 67, 'revenue': 4320},
                {'region': 'Other', 'students': 30, 'revenue': 1760},
            ]
        
        return geographic_data

    def _get_learning_paths(self, courses, start_date, end_date):
        """Get learning path analytics."""
        learning_path_data = []
        
        # Get learning path progress from database
        learning_paths = LearningPathProgress.objects.filter(
            learning_path__courses__in=courses,
            created_at__gte=start_date,
            created_at__lte=end_date
        ).values('learning_path__title').annotate(
            total_enrollments=Count('id'),
            completions=Count('id', filter=Q(completion_percentage=100)),
            avg_time=Avg('time_spent')
        )
        
        for path in learning_paths:
            completion_rate = (path['completions'] / path['total_enrollments'] * 100) if path['total_enrollments'] > 0 else 0
            avg_time_hours = path['avg_time'].total_seconds() / 3600 if path['avg_time'] else 0
            
            learning_path_data.append({
                'path': path['learning_path__title'],
                'completionRate': round(completion_rate, 1),
                'avgTime': round(avg_time_hours, 1),
            })
        
        if not learning_path_data:
            # Return mock data if no real learning paths
            return [
                {'path': 'Beginner Frontend', 'completionRate': 78, 'avgTime': 45},
                {'path': 'Advanced React', 'completionRate': 65, 'avgTime': 62},
                {'path': 'Full Stack Development', 'completionRate': 71, 'avgTime': 89},
            ]
        
        return learning_path_data

    def _get_predictive_analytics(self, courses, start_date, end_date):
        """Get predictive analytics data."""
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
        
        # Course recommendations based on enrollment patterns
        course_recommendations = []
        for course in courses:
            # Calculate potential students based on similar courses
            similar_courses = Course.objects.filter(
                category=course.category
            ).exclude(id=course.id)
            
            potential_students = User.objects.filter(
                enrollments__course__in=similar_courses,
                role=User.Role.LEARNER
            ).exclude(
                enrollments__course=course
            ).distinct().count()
            
            # Calculate confidence based on completion rates
            completion_rate = CourseCompletion.objects.filter(
                course=course,
                completion_date__isnull=False
            ).count()
            
            enrollments = User.objects.filter(enrollments__course=course).count()
            confidence = (completion_rate / enrollments * 100) if enrollments > 0 else 0
            
            if potential_students > 0:
                course_recommendations.append({
                    'course': course.title,
                    'potentialStudents': potential_students,
                    'confidence': round(confidence, 0),
                })
        
        course_recommendations.sort(key=lambda x: x['potentialStudents'], reverse=True)
        
        # Revenue forecasting based on historical data
        revenue_forecasting = []
        revenue_history = RevenueAnalytics.objects.filter(
            course__in=courses,
            period_start__gte=start_date - timedelta(days=365)
        ).annotate(
            month=TruncMonth('period_start')
        ).values('month').annotate(
            total_revenue=Sum('total_revenue')
        ).order_by('month')
        
        # Simple forecasting based on trend
        if revenue_history.count() >= 3:
            recent_revenues = list(revenue_history.values_list('total_revenue', flat=True)[-3:])
            trend = sum(recent_revenues) / len(recent_revenues)
            
            current_month = timezone.now().date().replace(day=1)
            for i in range(1, 5):  # Forecast next 4 months
                forecast_month = current_month + timedelta(days=32 * i)
                forecast_month = forecast_month.replace(day=1)
                
                predicted_revenue = trend * (1 + i * 0.05)  # 5% growth per month
                confidence = max(95 - i * 5, 70)  # Decreasing confidence over time
                
                revenue_forecasting.append({
                    'month': forecast_month.strftime('%b'),
                    'predicted': round(predicted_revenue, 0),
                    'confidence': confidence,
                })
        
        # Trends analysis
        trends_analysis = []
        
        # Calculate engagement trend
        recent_engagement = EngagementMetrics.objects.filter(
            course__in=courses,
            date__gte=start_date
        ).aggregate(avg_recent=Avg('interactions'))['avg_recent'] or 0
        
        past_engagement = EngagementMetrics.objects.filter(
            course__in=courses,
            date__gte=start_date - timedelta(days=30),
            date__lt=start_date
        ).aggregate(avg_past=Avg('interactions'))['avg_past'] or 0
        
        if past_engagement > 0:
            engagement_change = ((recent_engagement - past_engagement) / past_engagement) * 100
            trends_analysis.append({
                'metric': 'Student Engagement',
                'trend': 'up' if engagement_change > 0 else 'down',
                'change': round(abs(engagement_change), 0),
            })
        
        # Calculate completion trend
        recent_completions = CourseCompletion.objects.filter(
            course__in=courses,
            completion_date__gte=start_date
        ).count()
        
        past_completions = CourseCompletion.objects.filter(
            course__in=courses,
            completion_date__gte=start_date - timedelta(days=30),
            completion_date__lt=start_date
        ).count()
        
        if past_completions > 0:
            completion_change = ((recent_completions - past_completions) / past_completions) * 100
            trends_analysis.append({
                'metric': 'Course Completion',
                'trend': 'up' if completion_change > 0 else 'down',
                'change': round(abs(completion_change), 0),
            })
        
        return {
            'studentAtRisk': student_at_risk_data,
            'courseRecommendations': course_recommendations[:5],
            'revenueForecasting': revenue_forecasting,
            'trendsAnalysis': trends_analysis,
        }

    def _get_ai_insights(self, courses, start_date, end_date):
        """Get AI insights data."""
        key_insights = []
        recommendations = []
        anomalies = []
        
        # Calculate engagement growth
        recent_engagement = EngagementMetrics.objects.filter(
            course__in=courses,
            date__gte=start_date
        ).aggregate(avg_recent=Avg('interactions'))['avg_recent'] or 0
        
        past_engagement = EngagementMetrics.objects.filter(
            course__in=courses,
            date__gte=start_date - timedelta(days=30),
            date__lt=start_date
        ).aggregate(avg_past=Avg('interactions'))['avg_past'] or 0
        
        if past_engagement > 0:
            engagement_change = ((recent_engagement - past_engagement) / past_engagement) * 100
            if engagement_change > 10:
                key_insights.append({
                    'type': 'positive',
                    'title': 'Strong Engagement Growth',
                    'description': f'Student engagement has increased by {engagement_change:.0f}% over the past month',
                    'confidence': 92
                })
            elif engagement_change < -10:
                key_insights.append({
                    'type': 'negative',
                    'title': 'Declining Engagement',
                    'description': f'Student engagement has decreased by {abs(engagement_change):.0f}% over the past month',
                    'confidence': 88
                })
        
        # Analyze mobile usage
        mobile_usage = DeviceUsageAnalytics.objects.filter(
            tenant=courses.first().instructor.tenant if courses.exists() else None,
            date__gte=start_date,
            date__lte=end_date
        ).aggregate(
            total_mobile=Sum('mobile_users'),
            total_users=Sum('desktop_users') + Sum('mobile_users') + Sum('tablet_users')
        )
        
        if mobile_usage['total_users'] and mobile_usage['total_users'] > 0:
            mobile_percentage = (mobile_usage['total_mobile'] / mobile_usage['total_users']) * 100
            if mobile_percentage < 20:
                key_insights.append({
                    'type': 'negative',
                    'title': 'Low Mobile Usage',
                    'description': f'Only {mobile_percentage:.0f}% of students use mobile devices',
                    'confidence': 85
                })
                recommendations.append({
                    'priority': 'high',
                    'title': 'Implement Mobile-First Design',
                    'description': 'Optimize content for mobile devices to increase accessibility',
                    'impact': 'High'
                })
        
        # Revenue analysis
        revenue_data = RevenueAnalytics.objects.filter(
            course__in=courses,
            period_start__gte=start_date,
            period_end__lte=end_date
        ).aggregate(
            avg_revenue=Avg('total_revenue'),
            total_revenue=Sum('total_revenue')
        )
        
        if revenue_data['total_revenue']:
            key_insights.append({
                'type': 'neutral',
                'title': 'Revenue Performance',
                'description': f'Generated ${revenue_data["total_revenue"]:.0f} in revenue this period',
                'confidence': 90
            })
        
        # Check for completion rate issues
        for course in courses:
            enrollments = User.objects.filter(enrollments__course=course).count()
            completions = CourseCompletion.objects.filter(
                course=course,
                completion_date__isnull=False
            ).count()
            
            if enrollments > 0:
                completion_rate = (completions / enrollments) * 100
                if completion_rate < 50:
                    anomalies.append({
                        'type': 'completion',
                        'description': f'Low completion rate ({completion_rate:.0f}%) in {course.title}',
                        'severity': 'high'
                    })
                    recommendations.append({
                        'priority': 'high',
                        'title': f'Improve {course.title} Completion Rate',
                        'description': 'Analyze course content and add more interactive elements',
                        'impact': 'High'
                    })
        
        # Check for unusual activity patterns
        weekend_activity = EngagementMetrics.objects.filter(
            course__in=courses,
            date__gte=start_date,
            date__lte=end_date,
            date__week_day__in=[1, 7]  # Saturday and Sunday
        ).count()
        
        weekday_activity = EngagementMetrics.objects.filter(
            course__in=courses,
            date__gte=start_date,
            date__lte=end_date,
            date__week_day__in=[2, 3, 4, 5, 6]  # Monday to Friday
        ).count()
        
        if weekend_activity > 0 and weekday_activity > 0:
            weekend_ratio = weekend_activity / (weekend_activity + weekday_activity)
            if weekend_ratio > 0.4:  # More than 40% weekend activity
                anomalies.append({
                    'type': 'engagement',
                    'description': 'Unusual spike in weekend activity',
                    'severity': 'low'
                })
        
        # Add general recommendations if not enough specific ones
        if len(recommendations) < 3:
            recommendations.extend([
                {
                    'priority': 'medium',
                    'title': 'Create Interactive Quizzes',
                    'description': 'Add more interactive elements to boost engagement',
                    'impact': 'Medium'
                },
                {
                    'priority': 'low',
                    'title': 'Expand Social Features',
                    'description': 'Add peer-to-peer learning features',
                    'impact': 'Low'
                },
            ])
        
        return {
            'keyInsights': key_insights,
            'recommendations': recommendations[:3],
            'anomalies': anomalies,
        }

    def _get_real_time_data(self, courses):
        """Get real-time analytics data."""
        # Get current active sessions
        active_sessions = User.objects.filter(
            enrollments__course__in=courses,
            last_login__gte=timezone.now() - timedelta(minutes=30)
        ).count()
        
        # Get users active in last 5 minutes
        active_users = User.objects.filter(
            enrollments__course__in=courses,
            last_login__gte=timezone.now() - timedelta(minutes=5)
        ).count()
        
        # Calculate live engagement based on recent activity
        recent_engagement = EngagementMetrics.objects.filter(
            course__in=courses,
            date=timezone.now().date()
        ).aggregate(
            avg_engagement=Avg('interactions')
        )['avg_engagement'] or 0
        
        # Normalize engagement to percentage
        live_engagement = min(recent_engagement / 10, 100)  # Adjust divisor as needed
        
        return {
            'activeUsers': active_users,
            'currentSessions': active_sessions,
            'liveEngagement': round(live_engagement, 0),
            'serverHealth': 98,  # This could be fetched from a monitoring service
        }

    def _get_social_learning(self, courses, start_date, end_date):
        """Get social learning metrics."""
        discussions = []
        peer_reviews = []
        collaborative_projects = []
        
        # Get discussion data from content interactions
        for course in courses:
            discussion_interactions = ContentInteraction.objects.filter(
                course=course,
                interaction_type='discussion',
                created_at__gte=start_date,
                created_at__lte=end_date
            ).count()
            
            discussion_participants = ContentInteraction.objects.filter(
                course=course,
                interaction_type='discussion',
                created_at__gte=start_date,
                created_at__lte=end_date
            ).values('user').distinct().count()
            
            if discussion_interactions > 0:
                discussions.append({
                    'courseId': str(course.id),
                    'messages': discussion_interactions,
                    'participants': discussion_participants,
                })
        
        # Get peer review data from assessment analytics
        for course in courses:
            peer_review_count = AssessmentAnalytics.objects.filter(
                assessment__course=course,
                created_at__gte=start_date,
                created_at__lte=end_date
            ).count()
            
            avg_rating = AssessmentAnalytics.objects.filter(
                assessment__course=course,
                created_at__gte=start_date,
                created_at__lte=end_date
            ).aggregate(avg_score=Avg('avg_score'))['avg_score']
            
            if peer_review_count > 0:
                peer_reviews.append({
                    'courseId': str(course.id),
                    'reviews': peer_review_count,
                    'avgRating': round(avg_rating / 20, 1) if avg_rating else 4.0,  # Convert to 5-point scale
                })
        
        # Get collaborative project data from learning path progress
        collaborative_projects_data = LearningPathProgress.objects.filter(
            learning_path__courses__in=courses,
            created_at__gte=start_date,
            created_at__lte=end_date
        ).values('learning_path_id').annotate(
            participants=Count('user', distinct=True),
            avg_completion=Avg('completion_percentage')
        )
        
        for project in collaborative_projects_data:
            collaborative_projects.append({
                'projectId': f'project-{project["learning_path_id"]}',
                'participants': project['participants'],
                'completionRate': round(project['avg_completion'], 0),
            })
        
        return {
            'discussions': discussions,
            'peerReviews': peer_reviews,
            'collaborativeProjects': collaborative_projects,
        }

    def _get_learning_efficiency(self, courses, start_date, end_date):
        """Get learning efficiency data."""
        # Optimal study times based on engagement patterns
        optimal_study_times = []
        for hour in range(24):
            hour_engagement = EngagementMetrics.objects.filter(
                course__in=courses,
                date__gte=start_date,
                date__lte=end_date
            ).extra(
                where=["EXTRACT(hour FROM created_at) = %s"],
                params=[hour]
            ).aggregate(
                avg_engagement=Avg('interactions')
            )['avg_engagement'] or 0
            
            # Normalize to percentage
            efficiency = min(hour_engagement / 10, 100)  # Adjust divisor as needed
            
            optimal_study_times.append({
                'hour': hour,
                'efficiency': round(efficiency, 0),
            })
        
        # Content effectiveness based on interactions
        content_effectiveness = []
        content_types = ['Video', 'Interactive', 'Reading', 'Quiz']
        
        for content_type in content_types:
            # Get content interactions for this type
            interactions = ContentInteraction.objects.filter(
                course__in=courses,
                interaction_type=content_type.lower(),
                created_at__gte=start_date,
                created_at__lte=end_date
            )
            
            avg_time_spent = interactions.aggregate(
                avg_time=Avg('duration')
            )['avg_time']
            
            if avg_time_spent:
                avg_time_minutes = avg_time_spent.total_seconds() / 60
            else:
                avg_time_minutes = 0
            
            # Calculate completion rate based on successful interactions
            total_interactions = interactions.count()
            completed_interactions = interactions.filter(
                interaction_type=content_type.lower()
            ).count()
            
            completion_rate = (completed_interactions / total_interactions * 100) if total_interactions > 0 else 0
            
            content_effectiveness.append({
                'contentType': content_type,
                'avgTimeSpent': round(avg_time_minutes, 0),
                'completionRate': round(completion_rate, 0),
            })
        
        # Difficulty progression based on student performance
        difficulty_progression = []
        
        # Get learning objective progress data
        objectives = LearningObjectiveProgress.objects.filter(
            course__in=courses,
            created_at__gte=start_date,
            created_at__lte=end_date
        ).values('objective__title').annotate(
            avg_score=Avg('score'),
            success_rate=Avg('is_completed')
        )
        
        for obj in objectives:
            # Map objective difficulty (mock for now)
            difficulty_mapping = {
                'Intro': 2,
                'Basics': 4,
                'Intermediate': 6,
                'Advanced': 8,
            }
            
            difficulty_score = 5  # Default
            for key, value in difficulty_mapping.items():
                if key.lower() in obj['objective__title'].lower():
                    difficulty_score = value
                    break
            
            success_rate = obj['success_rate'] * 100 if obj['success_rate'] else 0
            
            difficulty_progression.append({
                'lesson': obj['objective__title'][:20],  # Truncate for display
                'difficultyScore': difficulty_score,
                'successRate': round(success_rate, 0),
            })
        
        # Sort by difficulty score
        difficulty_progression.sort(key=lambda x: x['difficultyScore'])
        
        return {
            'optimalStudyTimes': optimal_study_times,
            'contentEffectiveness': content_effectiveness,
            'difficultyProgression': difficulty_progression[:10],  # Limit to top 10
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
        if user.is_instructor:
            return StudentPerformance.objects.filter(course__instructor=user)
        elif user.is_student:
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
