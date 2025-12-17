import logging
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
    LearningEfficiency, SocialLearningMetrics, Report, Dashboard, DashboardWidget, Event,
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
    DashboardListSerializer, DashboardDetailSerializer, DashboardCreateUpdateSerializer,
    DashboardWidgetSerializer, WidgetCreateUpdateSerializer,
    StudentPerformanceSerializer, EngagementMetricsSerializer,
    AssessmentAnalyticsSerializer, LearningPathProgressSerializer,
    ContentInteractionSerializer, CourseCompletionSerializer,
    LearningObjectiveProgressSerializer, RevenueAnalyticsSerializer,
    DeviceUsageAnalyticsSerializer, GeographicAnalyticsSerializer,
    InstructorAnalyticsDashboardSerializer, PredictiveAnalyticsDataSerializer,
    AIInsightsDataSerializer, RealTimeDataSerializer, SocialLearningDataSerializer,
    LearningEfficiencyDataSerializer, EventLogSerializer
)
from .services import AnalyticsService
from apps.courses.models import Course
from apps.enrollments.models import Enrollment
from apps.users.models import User
from apps.users.permissions import IsAdmin
from apps.core.models import Tenant


@extend_schema(tags=['Analytics - Admin'])
class AdminAnalyticsView(APIView):
    """
    Main API view for admin analytics dashboard.
    Provides platform-wide analytics data across all tenants (for superusers)
    or tenant-specific data (for tenant admins).
    """
    permission_classes = [IsAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter(name='time_range', type=str, description='Time range filter (7d, 30d, 90d, 1y)'),
            OpenApiParameter(name='tenant_id', type=str, description='Filter by specific tenant (superuser only)'),
        ]
    )
    def get(self, request):
        """Get comprehensive admin analytics data."""
        user = request.user
        
        # Get filters
        time_range = request.query_params.get('time_range', '30d')
        tenant_id = request.query_params.get('tenant_id')
        
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
        analytics_data = self._build_admin_analytics_data(user, start_date, end_date, tenant_id)
        
        return Response(analytics_data)

    def _build_admin_analytics_data(self, user, start_date, end_date, tenant_id=None):
        """Build comprehensive admin analytics data structure."""
        
        # Determine tenant scope
        if user.is_superuser:
            if tenant_id:
                tenants = Tenant.objects.filter(id=tenant_id, is_active=True)
            else:
                tenants = Tenant.objects.filter(is_active=True)
        else:
            # Non-superuser admins can only see their own tenant
            tenants = Tenant.objects.filter(id=user.tenant_id, is_active=True) if user.tenant else Tenant.objects.none()
        
        # Overview metrics
        overview = self._get_overview_metrics(tenants, start_date, end_date)
        
        # User growth data
        user_growth = self._get_user_growth(tenants, start_date, end_date)
        
        # Tenant comparison
        tenant_comparison = self._get_tenant_comparison(tenants, start_date, end_date)
        
        # System activity
        system_activity = self._get_system_activity(tenants, start_date, end_date)
        
        # Course metrics
        course_metrics = self._get_course_metrics(tenants, start_date, end_date)
        
        # Real-time stats
        real_time_stats = self._get_real_time_stats(tenants)
        
        # Event distribution
        event_distribution = self._get_event_distribution(tenants, start_date, end_date)
        
        # Geographic distribution
        geographic_data = self._get_geographic_distribution(tenants, start_date, end_date)
        
        # Device usage
        device_usage = self._get_device_usage(tenants, start_date, end_date)
        
        return {
            'overview': overview,
            'userGrowth': user_growth,
            'tenantComparison': tenant_comparison,
            'systemActivity': system_activity,
            'courseMetrics': course_metrics,
            'realTimeStats': real_time_stats,
            'eventDistribution': event_distribution,
            'geographicData': geographic_data,
            'deviceUsage': device_usage,
        }

    def _get_overview_metrics(self, tenants, start_date, end_date):
        """Get overview metrics for admin dashboard."""
        tenant_ids = list(tenants.values_list('id', flat=True))
        
        # Total users across selected tenants
        total_users = User.objects.filter(tenant_id__in=tenant_ids).count()
        
        # Active users in last 24 hours (users who logged in)
        yesterday = timezone.now() - timedelta(hours=24)
        active_users_24h = Event.objects.filter(
            tenant_id__in=tenant_ids,
            event_type='USER_LOGIN',
            created_at__gte=yesterday
        ).values('user_id').distinct().count()
        
        # Total tenants
        total_tenants = tenants.count()
        
        # Total courses
        total_courses = Course.objects.filter(instructor__tenant_id__in=tenant_ids).count()
        
        # Total enrollments
        total_enrollments = Enrollment.objects.filter(
            course__instructor__tenant_id__in=tenant_ids
        ).count()
        
        # New users in date range
        new_users = User.objects.filter(
            tenant_id__in=tenant_ids,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).count()
        
        # New enrollments in date range
        new_enrollments = Enrollment.objects.filter(
            course__instructor__tenant_id__in=tenant_ids,
            enrolled_at__date__gte=start_date,
            enrolled_at__date__lte=end_date
        ).count()
        
        # Average completion rate
        completion_stats = Enrollment.objects.filter(
            course__instructor__tenant_id__in=tenant_ids
        ).aggregate(
            total=Count('id'),
            completed=Count('id', filter=Q(status=Enrollment.Status.COMPLETED))
        )
        avg_completion_rate = (
            (completion_stats['completed'] / completion_stats['total'] * 100) 
            if completion_stats['total'] > 0 else 0
        )
        
        return {
            'totalUsers': total_users,
            'activeUsers24h': active_users_24h,
            'totalTenants': total_tenants,
            'totalCourses': total_courses,
            'totalEnrollments': total_enrollments,
            'newUsers': new_users,
            'newEnrollments': new_enrollments,
            'avgCompletionRate': round(avg_completion_rate, 1),
        }

    def _get_user_growth(self, tenants, start_date, end_date):
        """Get user registration trends over time."""
        tenant_ids = list(tenants.values_list('id', flat=True))
        
        # Group registrations by date
        user_registrations = User.objects.filter(
            tenant_id__in=tenant_ids,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).annotate(
            date=TruncDate('created_at')
        ).values('date').annotate(
            count=Count('id')
        ).order_by('date')
        
        growth_data = []
        for item in user_registrations:
            growth_data.append({
                'date': item['date'].strftime('%Y-%m-%d'),
                'users': item['count'],
            })
        
        return growth_data

    def _get_tenant_comparison(self, tenants, start_date, end_date):
        """Get comparison metrics across tenants."""
        comparison_data = []
        
        for tenant in tenants:
            # Users count
            users_count = User.objects.filter(tenant=tenant).count()
            
            # Courses count
            courses_count = Course.objects.filter(instructor__tenant=tenant).count()
            
            # Enrollments count
            enrollments_count = Enrollment.objects.filter(
                course__instructor__tenant=tenant
            ).count()
            
            # Active enrollments
            active_enrollments = Enrollment.objects.filter(
                course__instructor__tenant=tenant,
                status=Enrollment.Status.ACTIVE
            ).count()
            
            # Completed enrollments
            completed_enrollments = Enrollment.objects.filter(
                course__instructor__tenant=tenant,
                status=Enrollment.Status.COMPLETED
            ).count()
            
            comparison_data.append({
                'id': str(tenant.id),
                'name': tenant.name,
                'slug': tenant.slug,
                'users': users_count,
                'courses': courses_count,
                'enrollments': enrollments_count,
                'activeEnrollments': active_enrollments,
                'completedEnrollments': completed_enrollments,
            })
        
        # Sort by enrollments descending
        comparison_data.sort(key=lambda x: x['enrollments'], reverse=True)
        
        return comparison_data

    def _get_system_activity(self, tenants, start_date, end_date):
        """Get system activity metrics."""
        tenant_ids = list(tenants.values_list('id', flat=True))
        
        # Events by type
        events_by_type = Event.objects.filter(
            tenant_id__in=tenant_ids,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).values('event_type').annotate(
            count=Count('id')
        ).order_by('-count')[:10]
        
        events_data = [
            {'type': item['event_type'], 'count': item['count']}
            for item in events_by_type
        ]
        
        # Login frequency by day
        login_frequency = Event.objects.filter(
            tenant_id__in=tenant_ids,
            event_type='USER_LOGIN',
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).annotate(
            date=TruncDate('created_at')
        ).values('date').annotate(
            count=Count('id')
        ).order_by('date')
        
        login_data = [
            {'date': item['date'].strftime('%Y-%m-%d'), 'logins': item['count']}
            for item in login_frequency
        ]
        
        # Peak usage times (by hour)
        from django.db.models.functions import ExtractHour
        peak_times = Event.objects.filter(
            tenant_id__in=tenant_ids,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).annotate(
            hour=ExtractHour('created_at')
        ).values('hour').annotate(
            count=Count('id')
        ).order_by('hour')
        
        peak_data = [
            {'hour': item['hour'], 'events': item['count']}
            for item in peak_times
        ]
        
        return {
            'eventsByType': events_data,
            'loginFrequency': login_data,
            'peakUsageTimes': peak_data,
        }

    def _get_course_metrics(self, tenants, start_date, end_date):
        """Get course-related metrics."""
        tenant_ids = list(tenants.values_list('id', flat=True))
        
        # Most popular courses (by enrollment)
        popular_courses = Course.objects.filter(
            instructor__tenant_id__in=tenant_ids
        ).annotate(
            enrollment_count=Count('enrollments')
        ).order_by('-enrollment_count')[:10]
        
        popular_courses_data = [
            {
                'id': str(course.id),
                'title': course.title,
                'instructor': course.instructor.get_full_name(),
                'tenant': course.instructor.tenant.name if course.instructor.tenant else 'N/A',
                'enrollments': course.enrollment_count,
            }
            for course in popular_courses
        ]
        
        # Course completion rates
        courses_with_completions = Course.objects.filter(
            instructor__tenant_id__in=tenant_ids
        ).annotate(
            total_enrollments=Count('enrollments'),
            completed_enrollments=Count('enrollments', filter=Q(enrollments__status=Enrollment.Status.COMPLETED))
        ).filter(total_enrollments__gt=0)
        
        completion_rates_data = []
        for course in courses_with_completions[:10]:
            completion_rate = (course.completed_enrollments / course.total_enrollments * 100)
            completion_rates_data.append({
                'id': str(course.id),
                'title': course.title,
                'completionRate': round(completion_rate, 1),
                'totalEnrollments': course.total_enrollments,
            })
        
        # Sort by completion rate
        completion_rates_data.sort(key=lambda x: x['completionRate'], reverse=True)
        
        # Courses by status
        courses_by_status = Course.objects.filter(
            instructor__tenant_id__in=tenant_ids
        ).values('status').annotate(
            count=Count('id')
        )
        
        status_data = [
            {'status': item['status'], 'count': item['count']}
            for item in courses_by_status
        ]
        
        return {
            'popularCourses': popular_courses_data,
            'completionRates': completion_rates_data,
            'coursesByStatus': status_data,
        }

    def _get_real_time_stats(self, tenants):
        """Get real-time statistics."""
        tenant_ids = list(tenants.values_list('id', flat=True))
        
        # Current active sessions (users with activity in last 15 minutes)
        fifteen_minutes_ago = timezone.now() - timedelta(minutes=15)
        active_sessions = Event.objects.filter(
            tenant_id__in=tenant_ids,
            created_at__gte=fifteen_minutes_ago
        ).values('session_id').distinct().count()
        
        # Current logged in users (unique users in last 15 minutes)
        current_logins = Event.objects.filter(
            tenant_id__in=tenant_ids,
            created_at__gte=fifteen_minutes_ago
        ).values('user_id').distinct().count()
        
        # Events in last hour
        one_hour_ago = timezone.now() - timedelta(hours=1)
        events_last_hour = Event.objects.filter(
            tenant_id__in=tenant_ids,
            created_at__gte=one_hour_ago
        ).count()
        
        # Latest events
        latest_events = Event.objects.filter(
            tenant_id__in=tenant_ids
        ).select_related('user', 'tenant').order_by('-created_at')[:10]
        
        latest_events_data = []
        for event in latest_events:
            latest_events_data.append({
                'id': str(event.id),
                'type': event.event_type,
                'user': event.user.email if event.user else 'Anonymous',
                'tenant': event.tenant.name if event.tenant else 'System',
                'timestamp': event.created_at.isoformat(),
            })
        
        return {
            'activeSessions': active_sessions,
            'currentLogins': current_logins,
            'eventsLastHour': events_last_hour,
            'latestEvents': latest_events_data,
        }

    def _get_event_distribution(self, tenants, start_date, end_date):
        """Get event type distribution."""
        tenant_ids = list(tenants.values_list('id', flat=True))
        
        # Events by type for pie chart
        event_distribution = Event.objects.filter(
            tenant_id__in=tenant_ids,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).values('event_type').annotate(
            count=Count('id')
        ).order_by('-count')
        
        total_events = sum(item['count'] for item in event_distribution)
        
        distribution_data = []
        for item in event_distribution:
            percentage = (item['count'] / total_events * 100) if total_events > 0 else 0
            distribution_data.append({
                'type': item['event_type'],
                'count': item['count'],
                'percentage': round(percentage, 1),
            })
        
        return distribution_data

    def _get_geographic_distribution(self, tenants, start_date, end_date):
        """Get geographic distribution of users."""
        tenant_ids = list(tenants.values_list('id', flat=True))
        
        # Get geographic data from events
        geo_data = Event.objects.filter(
            tenant_id__in=tenant_ids,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            country__isnull=False
        ).exclude(country='').values('country', 'region').annotate(
            users=Count('user_id', distinct=True),
            events=Count('id')
        ).order_by('-users')[:20]
        
        geographic_data = []
        for item in geo_data:
            geographic_data.append({
                'country': item['country'],
                'region': item['region'] or 'Unknown',
                'users': item['users'],
                'events': item['events'],
            })
        
        return geographic_data

    def _get_device_usage(self, tenants, start_date, end_date):
        """Get device usage statistics."""
        tenant_ids = list(tenants.values_list('id', flat=True))
        
        # Device distribution from events
        device_stats = Event.objects.filter(
            tenant_id__in=tenant_ids,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            device_type__isnull=False
        ).exclude(device_type='').values('device_type').annotate(
            users=Count('user_id', distinct=True),
            events=Count('id')
        ).order_by('-users')
        
        total_users = sum(item['users'] for item in device_stats)
        
        device_data = []
        for item in device_stats:
            percentage = (item['users'] / total_users * 100) if total_users > 0 else 0
            device_data.append({
                'device': item['device_type'].capitalize(),
                'users': item['users'],
                'events': item['events'],
                'percentage': round(percentage, 1),
            })
        
        return device_data


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
class DashboardDefinitionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing analytics dashboards with full CRUD operations.
    Supports creating, editing, cloning, and deleting custom dashboards.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return DashboardListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return DashboardCreateUpdateSerializer
        return DashboardDetailSerializer

    def get_queryset(self):
        """
        Return dashboards accessible to the current user.
        Users can see:
        - Their own dashboards
        - Shared dashboards within their tenant
        - Default dashboards for their role
        Staff users can see all dashboards in their tenant.
        """
        user = self.request.user
        queryset = Dashboard.objects.filter(tenant=user.tenant)
        
        # Staff can see all dashboards in their tenant
        if user.is_staff:
            return queryset.select_related('owner', 'tenant').prefetch_related('widgets')
        
        # Get IDs of default dashboards that include the user's role
        # Using Python filtering for SQLite/PostgreSQL compatibility
        default_dashboard_ids = [
            d.pk for d in queryset.filter(is_default=True)
            if user.role in (d.allowed_roles or [])
        ]
        
        # Filter based on visibility
        # Show: own dashboards, shared dashboards, or default dashboards matching user role
        queryset = queryset.filter(
            Q(owner=user) |
            Q(is_shared=True) |
            Q(pk__in=default_dashboard_ids)
        ).distinct()
        
        return queryset.select_related('owner', 'tenant').prefetch_related('widgets')

    def perform_create(self, serializer):
        """Set tenant and owner on create."""
        serializer.save(
            tenant=self.request.user.tenant,
            owner=self.request.user
        )

    def perform_update(self, serializer):
        """Ensure user can only update their own dashboards."""
        dashboard = self.get_object()
        if dashboard.owner != self.request.user and not self.request.user.is_staff:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only edit your own dashboards.")
        serializer.save()

    def perform_destroy(self, instance):
        """Ensure user can only delete their own dashboards."""
        if instance.owner != self.request.user and not self.request.user.is_staff:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only delete your own dashboards.")
        instance.delete()

    @extend_schema(
        request=None,
        responses={201: DashboardDetailSerializer},
        description="Clone an existing dashboard with all its widgets."
    )
    @action(detail=True, methods=['post'])
    def clone(self, request, pk=None):
        """
        Clone a dashboard and all its widgets.
        Creates a new dashboard with "(Copy)" appended to the name.
        """
        original = self.get_object()
        
        # Clone the dashboard
        cloned_dashboard = Dashboard.objects.create(
            tenant=request.user.tenant,
            owner=request.user,
            name=f"{original.name} (Copy)",
            description=original.description,
            is_default=False,
            is_shared=False,
            allowed_roles=original.allowed_roles,
            refresh_interval=original.refresh_interval,
            default_time_range=original.default_time_range,
            layout_config=original.layout_config,
        )
        
        # Clone all widgets
        for widget in original.widgets.all():
            DashboardWidget.objects.create(
                dashboard=cloned_dashboard,
                widget_type=widget.widget_type,
                title=widget.title,
                data_source=widget.data_source,
                config=widget.config,
                position_x=widget.position_x,
                position_y=widget.position_y,
                width=widget.width,
                height=widget.height,
                order=widget.order,
            )
        
        serializer = DashboardDetailSerializer(cloned_dashboard)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=DashboardCreateUpdateSerializer,
        responses={200: DashboardDetailSerializer},
        description="Set a dashboard as the default for specified roles."
    )
    @action(detail=True, methods=['post'])
    def set_default(self, request, pk=None):
        """
        Set a dashboard as the default for specified roles.
        Only staff/admin users can set default dashboards.
        """
        if not request.user.is_staff:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only staff users can set default dashboards.")
        
        dashboard = self.get_object()
        roles = request.data.get('roles', [])
        
        # Remove default status from other dashboards for these roles
        # (each role should have only one default dashboard)
        # Using Python filtering for SQLite/PostgreSQL compatibility
        for role in roles:
            conflicting_dashboards = [
                d.pk for d in Dashboard.objects.filter(
                    tenant=request.user.tenant,
                    is_default=True,
                ).exclude(pk=dashboard.pk)
                if role in (d.allowed_roles or [])
            ]
            if conflicting_dashboards:
                Dashboard.objects.filter(pk__in=conflicting_dashboards).update(is_default=False)
        
        dashboard.is_default = True
        dashboard.allowed_roles = roles
        dashboard.save()
        
        serializer = DashboardDetailSerializer(dashboard)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def share(self, request, pk=None):
        """Toggle sharing status of a dashboard."""
        dashboard = self.get_object()
        
        if dashboard.owner != request.user and not request.user.is_staff:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only share your own dashboards.")
        
        is_shared = request.data.get('is_shared', not dashboard.is_shared)
        dashboard.is_shared = is_shared
        dashboard.save()
        
        serializer = DashboardDetailSerializer(dashboard)
        return Response(serializer.data)


@extend_schema(tags=['Analytics - Widgets'])
class DashboardWidgetViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing widgets within a dashboard.
    Nested under dashboards: /dashboards/{dashboard_id}/widgets/
    """
    serializer_class = DashboardWidgetSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Return widgets for the specified dashboard."""
        dashboard_id = self.kwargs.get('dashboard_pk')
        return DashboardWidget.objects.filter(
            dashboard_id=dashboard_id,
            dashboard__tenant=self.request.user.tenant
        ).order_by('order', 'position_y', 'position_x')

    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action in ['create', 'update', 'partial_update']:
            return WidgetCreateUpdateSerializer
        return DashboardWidgetSerializer

    def perform_create(self, serializer):
        """Create widget within the specified dashboard."""
        dashboard_id = self.kwargs.get('dashboard_pk')
        dashboard = get_object_or_404(
            Dashboard, 
            pk=dashboard_id, 
            tenant=self.request.user.tenant
        )
        
        # Check ownership
        if dashboard.owner != self.request.user and not self.request.user.is_staff:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only add widgets to your own dashboards.")
        
        serializer.save(dashboard=dashboard)

    def perform_update(self, serializer):
        """Update widget, checking dashboard ownership."""
        widget = self.get_object()
        if widget.dashboard.owner != self.request.user and not self.request.user.is_staff:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only edit widgets in your own dashboards.")
        serializer.save()

    def perform_destroy(self, instance):
        """Delete widget, checking dashboard ownership."""
        if instance.dashboard.owner != self.request.user and not self.request.user.is_staff:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only delete widgets from your own dashboards.")
        instance.delete()

    @extend_schema(
        request={'application/json': {'type': 'array', 'items': {'type': 'object'}}},
        responses={200: DashboardWidgetSerializer(many=True)},
        description="Bulk update widget positions/sizes for drag-and-drop operations."
    )
    @action(detail=False, methods=['post'])
    def bulk_update_positions(self, request, dashboard_pk=None):
        """
        Bulk update widget positions after drag-and-drop.
        Expects a list of {id, position_x, position_y, width, height} objects.
        """
        dashboard = get_object_or_404(
            Dashboard, 
            pk=dashboard_pk, 
            tenant=request.user.tenant
        )
        
        if dashboard.owner != request.user and not request.user.is_staff:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You can only update widgets in your own dashboards.")
        
        updates = request.data
        if not isinstance(updates, list):
            return Response(
                {'error': 'Expected a list of widget position updates'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        updated_widgets = []
        for update in updates:
            widget_id = update.get('id')
            if not widget_id:
                continue
            
            try:
                widget = DashboardWidget.objects.get(
                    id=widget_id, 
                    dashboard=dashboard
                )
                
                if 'position_x' in update:
                    widget.position_x = update['position_x']
                if 'position_y' in update:
                    widget.position_y = update['position_y']
                if 'width' in update:
                    widget.width = update['width']
                if 'height' in update:
                    widget.height = update['height']
                if 'order' in update:
                    widget.order = update['order']
                
                widget.save()
                updated_widgets.append(widget)
            except DashboardWidget.DoesNotExist:
                continue
        
        serializer = DashboardWidgetSerializer(updated_widgets, many=True)
        return Response(serializer.data)


@extend_schema(tags=['Analytics - Widget Data'])
class WidgetDataView(APIView):
    """
    API view for fetching widget data based on data source.
    This endpoint returns the actual data for a widget to display.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(name='time_range', type=str, description='Time range (7d, 30d, 90d, 1y)'),
            OpenApiParameter(name='tenant_id', type=str, description='Filter by tenant (admin only)'),
        ],
        responses={200: {'type': 'object'}},
    )
    def get(self, request, widget_id=None):
        """
        Get data for a specific widget.
        The data returned depends on the widget's data_source.
        """
        widget = get_object_or_404(
            DashboardWidget,
            pk=widget_id,
            dashboard__tenant=request.user.tenant
        )
        
        # Get query parameters
        time_range = request.query_params.get('time_range', '30d')
        tenant_id = request.query_params.get('tenant_id')
        
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
        
        # Get data based on data source
        data = self._get_widget_data(
            widget.data_source,
            request.user,
            start_date,
            end_date,
            tenant_id,
            widget.config
        )
        
        return Response({
            'widget_id': str(widget.id),
            'data_source': widget.data_source,
            'time_range': time_range,
            'data': data
        })

    def _get_widget_data(self, data_source, user, start_date, end_date, tenant_id, config):
        """
        Fetch data based on the data source type.
        Maps data sources to existing analytics methods.
        """
        # Determine tenant scope
        if user.is_superuser and tenant_id:
            tenants = Tenant.objects.filter(id=tenant_id, is_active=True)
        elif user.is_superuser:
            tenants = Tenant.objects.filter(is_active=True)
        else:
            tenants = Tenant.objects.filter(id=user.tenant_id) if user.tenant else Tenant.objects.none()
        
        tenant_ids = list(tenants.values_list('id', flat=True))
        
        # Route to appropriate data fetcher
        data_fetchers = {
            'user_growth': self._get_user_growth_data,
            'enrollment_stats': self._get_enrollment_stats,
            'course_metrics': self._get_course_metrics,
            'completion_rates': self._get_completion_rates,
            'login_frequency': self._get_login_frequency,
            'peak_usage': self._get_peak_usage,
            'tenant_comparison': self._get_tenant_comparison,
            'device_usage': self._get_device_usage,
            'geographic_data': self._get_geographic_data,
            'events_by_type': self._get_events_by_type,
            'popular_courses': self._get_popular_courses,
            'active_users': self._get_active_users,
            'recent_activity': self._get_recent_activity,
        }
        
        fetcher = data_fetchers.get(data_source)
        if fetcher:
            return fetcher(tenant_ids, start_date, end_date, config)
        
        return {'error': f'Unknown data source: {data_source}'}

    def _get_user_growth_data(self, tenant_ids, start_date, end_date, config):
        """Get user registration trends over time."""
        user_registrations = User.objects.filter(
            tenant_id__in=tenant_ids,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).annotate(
            date=TruncDate('created_at')
        ).values('date').annotate(
            count=Count('id')
        ).order_by('date')
        
        return [
            {'date': item['date'].strftime('%Y-%m-%d'), 'value': item['count']}
            for item in user_registrations
        ]

    def _get_enrollment_stats(self, tenant_ids, start_date, end_date, config):
        """Get enrollment statistics."""
        enrollments = Enrollment.objects.filter(
            course__instructor__tenant_id__in=tenant_ids,
            enrolled_at__date__gte=start_date,
            enrolled_at__date__lte=end_date
        ).annotate(
            date=TruncDate('enrolled_at')
        ).values('date').annotate(
            count=Count('id')
        ).order_by('date')
        
        return [
            {'date': item['date'].strftime('%Y-%m-%d'), 'value': item['count']}
            for item in enrollments
        ]

    def _get_course_metrics(self, tenant_ids, start_date, end_date, config):
        """Get course performance metrics."""
        courses = Course.objects.filter(
            instructor__tenant_id__in=tenant_ids
        ).annotate(
            enrollment_count=Count('enrollments'),
            completion_count=Count('enrollments', filter=Q(enrollments__status=Enrollment.Status.COMPLETED))
        ).order_by('-enrollment_count')[:10]
        
        return [
            {
                'title': course.title,
                'enrollments': course.enrollment_count,
                'completions': course.completion_count,
                'completion_rate': round((course.completion_count / course.enrollment_count * 100), 1) if course.enrollment_count > 0 else 0
            }
            for course in courses
        ]

    def _get_completion_rates(self, tenant_ids, start_date, end_date, config):
        """Get completion rate trends."""
        completion_data = Enrollment.objects.filter(
            course__instructor__tenant_id__in=tenant_ids,
            enrolled_at__date__gte=start_date,
            enrolled_at__date__lte=end_date
        ).annotate(
            month=TruncMonth('enrolled_at')
        ).values('month').annotate(
            total=Count('id'),
            completed=Count('id', filter=Q(status=Enrollment.Status.COMPLETED))
        ).order_by('month')
        
        return [
            {
                'date': item['month'].strftime('%Y-%m'),
                'rate': round((item['completed'] / item['total'] * 100), 1) if item['total'] > 0 else 0
            }
            for item in completion_data
        ]

    def _get_login_frequency(self, tenant_ids, start_date, end_date, config):
        """Get login frequency data."""
        login_data = Event.objects.filter(
            tenant_id__in=tenant_ids,
            event_type='USER_LOGIN',
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).annotate(
            date=TruncDate('created_at')
        ).values('date').annotate(
            count=Count('id')
        ).order_by('date')
        
        return [
            {'date': item['date'].strftime('%Y-%m-%d'), 'value': item['count']}
            for item in login_data
        ]

    def _get_peak_usage(self, tenant_ids, start_date, end_date, config):
        """Get peak usage times by hour."""
        from django.db.models.functions import ExtractHour
        
        peak_data = Event.objects.filter(
            tenant_id__in=tenant_ids,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).annotate(
            hour=ExtractHour('created_at')
        ).values('hour').annotate(
            count=Count('id')
        ).order_by('hour')
        
        return [
            {'hour': item['hour'], 'value': item['count']}
            for item in peak_data
        ]

    def _get_tenant_comparison(self, tenant_ids, start_date, end_date, config):
        """Get cross-tenant comparison metrics."""
        tenants = Tenant.objects.filter(id__in=tenant_ids, is_active=True)
        
        comparison_data = []
        for tenant in tenants:
            users_count = User.objects.filter(tenant=tenant).count()
            courses_count = Course.objects.filter(instructor__tenant=tenant).count()
            enrollments_count = Enrollment.objects.filter(
                course__instructor__tenant=tenant
            ).count()
            
            comparison_data.append({
                'name': tenant.name,
                'users': users_count,
                'courses': courses_count,
                'enrollments': enrollments_count,
            })
        
        return comparison_data

    def _get_device_usage(self, tenant_ids, start_date, end_date, config):
        """Get device usage distribution."""
        device_stats = Event.objects.filter(
            tenant_id__in=tenant_ids,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            device_type__isnull=False
        ).exclude(device_type='').values('device_type').annotate(
            count=Count('id')
        ).order_by('-count')
        
        return [
            {'device': item['device_type'].capitalize(), 'value': item['count']}
            for item in device_stats
        ]

    def _get_geographic_data(self, tenant_ids, start_date, end_date, config):
        """Get geographic distribution of users."""
        geo_data = Event.objects.filter(
            tenant_id__in=tenant_ids,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            country__isnull=False
        ).exclude(country='').values('country').annotate(
            users=Count('user_id', distinct=True)
        ).order_by('-users')[:20]
        
        return [
            {'country': item['country'], 'value': item['users']}
            for item in geo_data
        ]

    def _get_events_by_type(self, tenant_ids, start_date, end_date, config):
        """Get event distribution by type."""
        event_data = Event.objects.filter(
            tenant_id__in=tenant_ids,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).values('event_type').annotate(
            count=Count('id')
        ).order_by('-count')[:10]
        
        return [
            {'type': item['event_type'], 'value': item['count']}
            for item in event_data
        ]

    def _get_popular_courses(self, tenant_ids, start_date, end_date, config):
        """Get most popular courses by enrollment."""
        courses = Course.objects.filter(
            instructor__tenant_id__in=tenant_ids
        ).annotate(
            enrollment_count=Count('enrollments')
        ).order_by('-enrollment_count')[:10]
        
        return [
            {
                'title': course.title,
                'instructor': course.instructor.get_full_name(),
                'enrollments': course.enrollment_count,
            }
            for course in courses
        ]

    def _get_active_users(self, tenant_ids, start_date, end_date, config):
        """Get active user counts over time."""
        active_users = Event.objects.filter(
            tenant_id__in=tenant_ids,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).annotate(
            date=TruncDate('created_at')
        ).values('date').annotate(
            active_users=Count('user_id', distinct=True)
        ).order_by('date')
        
        return [
            {'date': item['date'].strftime('%Y-%m-%d'), 'value': item['active_users']}
            for item in active_users
        ]

    def _get_recent_activity(self, tenant_ids, start_date, end_date, config):
        """Get recent activity feed."""
        events = Event.objects.filter(
            tenant_id__in=tenant_ids,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).select_related('user').order_by('-created_at')[:20]
        
        return [
            {
                'type': event.event_type,
                'user': event.user.email if event.user else 'Anonymous',
                'timestamp': event.created_at.isoformat(),
            }
            for event in events
        ]


@extend_schema(tags=['Analytics - Widget Meta'])
class WidgetMetaView(APIView):
    """
    API view for getting widget metadata (types and data sources).
    """
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=['get'])
    def get(self, request):
        """Get available widget types and data sources."""
        widget_types = [
            {
                'value': choice[0],
                'label': choice[1],
                'description': self._get_widget_type_description(choice[0])
            }
            for choice in DashboardWidget.WidgetType.choices
        ]
        
        data_sources = [
            {
                'value': choice[0],
                'label': choice[1],
                'description': self._get_data_source_description(choice[0])
            }
            for choice in DashboardWidget.DataSource.choices
        ]
        
        return Response({
            'widget_types': widget_types,
            'data_sources': data_sources,
        })

    def _get_widget_type_description(self, widget_type):
        """Get description for a widget type."""
        descriptions = {
            'stat_card': 'Display a single KPI with optional trend indicator',
            'line_chart': 'Time-series data with line visualization',
            'bar_chart': 'Categorical data with bar visualization',
            'pie_chart': 'Distribution data with pie/donut chart',
            'area_chart': 'Time-series with filled area under the line',
            'table': 'Tabular data display with sorting and pagination',
            'progress_ring': 'Circular progress indicator for single metric',
            'leaderboard': 'Ranked list of items',
        }
        return descriptions.get(widget_type, '')

    def _get_data_source_description(self, data_source):
        """Get description for a data source."""
        descriptions = {
            'user_growth': 'User registration trends over time',
            'enrollment_stats': 'Course enrollment statistics',
            'course_metrics': 'Course performance metrics',
            'completion_rates': 'Course completion rate trends',
            'login_frequency': 'User login activity over time',
            'peak_usage': 'Peak usage hours distribution',
            'tenant_comparison': 'Cross-tenant comparison metrics',
            'device_usage': 'Device type distribution',
            'geographic_data': 'User geographic distribution',
            'events_by_type': 'Event type breakdown',
            'popular_courses': 'Top courses by enrollment',
            'active_users': 'Active user counts over time',
            'recent_activity': 'Recent user activity feed',
        }
        return descriptions.get(data_source, '')
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
        # Total students: distinct users enrolled in instructor's courses
        total_students = User.objects.filter(
            enrollments__course__in=courses,
            role=User.Role.LEARNER
        ).distinct().count()
        
        # Active students: distinct users with ACTIVE enrollment status
        active_students = User.objects.filter(
            enrollments__course__in=courses,
            enrollments__status=Enrollment.Status.ACTIVE,
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
        
        # Get average completion rate per course (consistent with Dashboard)
        # Dashboard calculates completion rate per course, then averages them
        course_completion_rates = []
        for course in courses:
            total_enrollments_course = Enrollment.objects.filter(course=course).count()
            completed_enrollments = Enrollment.objects.filter(
                course=course,
                status=Enrollment.Status.COMPLETED
            ).count()
            if total_enrollments_course > 0:
                rate = (completed_enrollments / total_enrollments_course) * 100
                course_completion_rates.append(rate)
        
        completion_rate = sum(course_completion_rates) / len(course_completion_rates) if course_completion_rates else 0
        
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
            'activeStudents': active_students,
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
            
            # Get completion rate using Enrollment.Status.COMPLETED (consistent with Dashboard)
            total_enrollments = Enrollment.objects.filter(course=course).count()
            completed_enrollments = Enrollment.objects.filter(
                course=course,
                status=Enrollment.Status.COMPLETED
            ).count()
            
            completion_rate = (completed_enrollments / total_enrollments * 100) if total_enrollments > 0 else 0
            
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
        
        # Top students (use __date for proper date comparison with datetime fields)
        top_students = StudentPerformance.objects.filter(
            course__in=courses,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
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
        """Get student distribution data using Enrollment status (consistent with Dashboard)."""
        # Total students enrolled in any of the instructor's courses
        total_students = User.objects.filter(
            enrollments__course__in=courses,
            role=User.Role.LEARNER
        ).distinct().count()
        
        # Active students: those with Enrollment.Status.ACTIVE
        active_students = User.objects.filter(
            enrollments__course__in=courses,
            enrollments__status=Enrollment.Status.ACTIVE,
            role=User.Role.LEARNER
        ).distinct().count()
        
        # Completed students: those with Enrollment.Status.COMPLETED
        completed_students = User.objects.filter(
            enrollments__course__in=courses,
            enrollments__status=Enrollment.Status.COMPLETED,
            role=User.Role.LEARNER
        ).distinct().count()
        
        # Dropped students: those with Enrollment.Status.CANCELLED (dropped or removed)
        dropped_students = User.objects.filter(
            enrollments__course__in=courses,
            enrollments__status=Enrollment.Status.CANCELLED,
            role=User.Role.LEARNER
        ).distinct().count()
        
        # Inactive students: total - active - completed - dropped
        inactive_students = max(0, total_students - active_students - completed_students - dropped_students)
        
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
        from apps.learning_paths.models import LearningPath, LearningPathStep
        from django.contrib.contenttypes.models import ContentType
        
        # Get learning paths that include any of the instructor's courses
        course_ids = list(courses.values_list('id', flat=True))
        
        # LearningPath uses GenericForeignKey via LearningPathStep to link to courses
        # First, find LearningPathStep entries that link to the instructor's courses
        course_content_type = ContentType.objects.get_for_model(courses.model)
        
        # Get learning path IDs that contain the instructor's courses
        learning_path_ids = LearningPathStep.objects.filter(
            content_type=course_content_type,
            object_id__in=course_ids
        ).values_list('learning_path_id', flat=True).distinct()
        
        # Query learning path progress data for those learning paths
        # Note: LearningPathProgress doesn't have completion_percentage or actual_time_spent fields
        # It has status field and progress_percentage property calculated from step_progress
        learning_path_data = LearningPathProgress.objects.filter(
            learning_path_id__in=learning_path_ids,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).values('learning_path__title').annotate(
            total_count=Count('id'),
            completed_count=Count('id', filter=Q(status='COMPLETED'))
        ).order_by('-completed_count')
        
        result = []
        for item in learning_path_data:
            # Calculate completion rate as percentage of completed progress records
            total = item['total_count'] or 1
            completed = item['completed_count'] or 0
            completion_rate = (completed / total) * 100
            
            result.append({
                'path': item['learning_path__title'],
                'completionRate': round(completion_rate, 1),
                'avgTime': 0,  # Time tracking not available in current model
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
        from apps.users.models import User
        user = self.request.user
        if user.role == User.Role.INSTRUCTOR:
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
        from apps.users.models import User
        user = self.request.user
        if user.role == User.Role.INSTRUCTOR:
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


@extend_schema(tags=['Analytics - Event Log'])
class EventLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing and filtering event logs (admin only).
    Provides list and detail views with filtering by event type, user, date range.
    """
    serializer_class = EventLogSerializer
    permission_classes = [IsAdmin]

    def get_queryset(self):
        """
        Return events filtered by tenant and optional query parameters.
        """
        user = self.request.user
        queryset = Event.objects.select_related('user', 'tenant')

        # Filter by tenant for non-superusers
        if not user.is_superuser and hasattr(user, 'tenant') and user.tenant:
            queryset = queryset.filter(tenant=user.tenant)

        # Filter by event type
        event_type = self.request.query_params.get('event_type')
        if event_type:
            queryset = queryset.filter(event_type=event_type)

        # Filter by user ID
        user_id = self.request.query_params.get('user_id')
        if user_id:
            queryset = queryset.filter(user_id=user_id)

        # Filter by date range
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)

        # Filter by device type
        device_type = self.request.query_params.get('device_type')
        if device_type:
            queryset = queryset.filter(device_type=device_type)

        # Filter by country
        country = self.request.query_params.get('country')
        if country:
            queryset = queryset.filter(country=country)

        # Search in context_data (basic search)
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(user__email__icontains=search) |
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search) |
                Q(session_id__icontains=search) |
                Q(ip_address__icontains=search)
            )

        return queryset.order_by('-created_at')

    @extend_schema(
        parameters=[
            OpenApiParameter(name='event_type', type=str, description='Filter by event type'),
            OpenApiParameter(name='user_id', type=str, description='Filter by user ID'),
            OpenApiParameter(name='start_date', type=str, description='Filter by start date (YYYY-MM-DD)'),
            OpenApiParameter(name='end_date', type=str, description='Filter by end date (YYYY-MM-DD)'),
            OpenApiParameter(name='device_type', type=str, description='Filter by device type'),
            OpenApiParameter(name='country', type=str, description='Filter by country'),
            OpenApiParameter(name='search', type=str, description='Search in user email, name, session ID, or IP'),
        ]
    )
    def list(self, request, *args, **kwargs):
        """List events with pagination and filtering."""
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=['get'])
    def event_types(self, request):
        """Return available event types for filtering."""
        event_types = [
            {'value': choice[0], 'label': choice[1]}
            for choice in Event.EVENT_TYPES
        ]
        return Response(event_types)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Return event statistics for the dashboard."""
        queryset = self.get_queryset()
        
        # Get date range from params or default to last 7 days
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=7)
        
        start_date_param = request.query_params.get('start_date')
        end_date_param = request.query_params.get('end_date')
        if start_date_param:
            start_date = start_date_param
        if end_date_param:
            end_date = end_date_param

        # Total events
        total_events = queryset.count()

        # Events by type
        events_by_type = queryset.values('event_type').annotate(
            count=Count('id')
        ).order_by('-count')[:10]

        # Events by day
        events_by_day = queryset.filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).annotate(
            date=TruncDate('created_at')
        ).values('date').annotate(
            count=Count('id')
        ).order_by('date')

        # Events by device type
        events_by_device = queryset.exclude(
            device_type__isnull=True
        ).values('device_type').annotate(
            count=Count('id')
        ).order_by('-count')

        return Response({
            'total_events': total_events,
            'events_by_type': list(events_by_type),
            'events_by_day': list(events_by_day),
            'events_by_device': list(events_by_device),
        })


@extend_schema(tags=['Analytics - Learner Insights'])
class LearnerInsightsView(APIView):
    """
    API view for learner insights and personalized analytics.
    
    Provides comprehensive analytics data for individual learners including:
    - Overview statistics (courses enrolled, completed, learning hours, streak)
    - Learning activity patterns and engagement metrics
    - Course progress across all enrolled courses
    - Assessment performance analytics
    - Learning patterns and study habits
    - Personalized recommendations
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='tenant_id',
                type=str,
                description='Filter insights by tenant (optional, defaults to user tenant)',
                required=False
            ),
        ],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'user_id': {'type': 'string'},
                    'generated_at': {'type': 'string', 'format': 'date-time'},
                    'overview': {
                        'type': 'object',
                        'properties': {
                            'total_courses_enrolled': {'type': 'integer'},
                            'courses_completed': {'type': 'integer'},
                            'courses_in_progress': {'type': 'integer'},
                            'overall_progress_percentage': {'type': 'number'},
                            'total_learning_hours': {'type': 'number'},
                            'current_streak_days': {'type': 'integer'},
                            'certificates_earned': {'type': 'integer'},
                        }
                    },
                    'learning_activity': {'type': 'object'},
                    'course_progress': {'type': 'array'},
                    'assessment_performance': {'type': 'object'},
                    'learning_patterns': {'type': 'object'},
                    'recommendations': {'type': 'object'},
                }
            }
        },
        description="Get comprehensive learner insights and analytics for the authenticated user."
    )
    def get(self, request):
        """
        Get learner insights for the authenticated user.
        
        Returns personalized analytics including:
        - overview: Summary statistics (courses, progress, hours, streak, certificates)
        - learning_activity: Recent activity patterns and engagement
        - course_progress: Detailed progress for each enrolled course
        - assessment_performance: Assessment scores, trends, and performance by type
        - learning_patterns: Study habits, optimal times, device usage
        - recommendations: Personalized suggestions for improvement
        """
        from .services import LearnerInsightsService
        
        user = request.user
        
        # Get optional tenant filter
        tenant = None
        tenant_id = request.query_params.get('tenant_id')
        if tenant_id:
            try:
                tenant = Tenant.objects.get(id=tenant_id, is_active=True)
            except Tenant.DoesNotExist:
                pass
        elif user.tenant:
            tenant = user.tenant
        
        try:
            insights = LearnerInsightsService.get_learner_insights(user, tenant)
            return Response(insights)
        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.exception("Failed to generate learner insights: %s", str(e))
            return Response(
                {'error': 'Failed to generate learner insights'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
