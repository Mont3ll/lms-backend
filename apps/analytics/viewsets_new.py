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


@extend_schema(tags=['Analytics'])
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


@extend_schema(tags=['Analytics'])
class ReportDataView(APIView):
    """
    API view for generating and retrieving analytics data.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        """Generate analytics data based on filters."""
        filters = request.data.get('filters', {})
        
        # Mock analytics data structure
        data = {
            'overview': {
                'total_students': 150,
                'total_courses': 5,
                'completion_rate': 75.5,
                'avg_score': 82.3
            },
            'student_performance': [],
            'course_analytics': [],
            'engagement_metrics': []
        }
        
        return Response(data)


@extend_schema(tags=['Analytics'])
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


@extend_schema(tags=['Analytics'])
class CourseAnalyticsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for course analytics data.
    """
    serializer_class = CourseAnalyticsSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_instructor:
            return CourseAnalytics.objects.filter(tenant=user.tenant)
        return CourseAnalytics.objects.none()


@extend_schema(tags=['Analytics'])
class StudentEngagementViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for student engagement metrics.
    """
    serializer_class = StudentEngagementMetricSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_instructor:
            return StudentEngagementMetric.objects.filter(tenant=user.tenant)
        return StudentEngagementMetric.objects.none()


@extend_schema(tags=['Analytics'])
class InstructorAnalyticsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for instructor analytics data.
    """
    serializer_class = InstructorAnalyticsSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_instructor:
            return InstructorAnalytics.objects.filter(
                instructor=user,
                tenant=user.tenant
            )
        return InstructorAnalytics.objects.none()
