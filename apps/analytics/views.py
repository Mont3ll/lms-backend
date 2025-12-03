import logging
import uuid
from rest_framework import viewsets, permissions, status, generics, serializers # Added serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied # Import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.utils import timezone

from .models import Report, Dashboard, Event, Tenant
from .serializers import ReportSerializer, DashboardSerializer, ReportDataSerializer, EventSerializer
from .services import ReportGeneratorService, ReportGenerationError, ExportService, AnalyticsService
from apps.users.permissions import IsAdminOrTenantAdmin, IsInstructorOrAdmin
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

logger = logging.getLogger(__name__)

@extend_schema(tags=['Admin - Analytics'])
class ReportViewSet(viewsets.ModelViewSet):
    serializer_class = ReportSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrTenantAdmin]
    lookup_field = 'slug'
    lookup_value_regex = r'[-\w]+' # <-- USED RAW STRING (r'')

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Report.objects.none()
        user = self.request.user
        tenant = self.request.tenant
        if not user.is_authenticated: return Report.objects.none()
        if user.is_superuser:
            return Report.objects.all().select_related('tenant')
        elif user.is_staff and tenant:
            return Report.objects.filter(Q(tenant=tenant) | Q(tenant__isnull=True)).select_related('tenant')
        return Report.objects.none()

    def perform_create(self, serializer):
        tenant = self.request.tenant
        req_tenant_id = self.request.data.get('tenant')
        save_tenant = None
        if self.request.user.is_superuser:
            if req_tenant_id: save_tenant = get_object_or_404(Tenant, pk=req_tenant_id)
        elif tenant:
             if req_tenant_id and str(tenant.id) != str(req_tenant_id):
                 raise serializers.ValidationError({"tenant": "Tenant Admins can only create reports for their own tenant."})
             save_tenant = tenant
        else:
            raise PermissionDenied("Cannot determine tenant context for report creation.")
        serializer.save(tenant=save_tenant)


@extend_schema(tags=['Admin - Analytics'])
class DashboardViewSet(viewsets.ModelViewSet):
    serializer_class = DashboardSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrTenantAdmin]
    lookup_field = 'slug'
    lookup_value_regex = r'[-\w]+' # <-- USED RAW STRING (r'')

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Dashboard.objects.none()
        user = self.request.user
        tenant = self.request.tenant
        if not user.is_authenticated: return Dashboard.objects.none()
        if user.is_superuser:
            return Dashboard.objects.all().select_related('tenant')
        elif user.is_staff and tenant:
             return Dashboard.objects.filter(tenant=tenant).select_related('tenant')
        return Dashboard.objects.none()

    def perform_create(self, serializer):
        tenant = self.request.tenant
        if not tenant and not self.request.user.is_superuser: # Superuser might create for specific tenant if passed
             tenant_id = self.request.data.get('tenant')
             if self.request.user.is_superuser and tenant_id:
                 tenant = get_object_or_404(Tenant, pk=tenant_id)
             else:
                  raise PermissionDenied("Tenant context required.")
        serializer.save(tenant=tenant)


@extend_schema(
    tags=['Analytics Data'],
    summary="Generate Report Data",
    description="Generates and returns data for a specific report definition, applying optional filters.",
    parameters=[
        OpenApiParameter(name='report_slug', description='Slug of the report definition', required=True, type=OpenApiTypes.STR, location=OpenApiParameter.PATH, pattern=r'^[-\w]+$'), # Added pattern
        OpenApiParameter(name='start_date', description='Filter data after this date (YYYY-MM-DD)', required=False, type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY),
        OpenApiParameter(name='end_date', description='Filter data before this date (YYYY-MM-DD)', required=False, type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY),
        OpenApiParameter(name='course_id', description='Filter data by Course UUID', required=False, type=OpenApiTypes.UUID, location=OpenApiParameter.QUERY),
    ],
    responses={ 200: ReportDataSerializer, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT, 404: OpenApiTypes.OBJECT, 500: OpenApiTypes.OBJECT }
)
class GenerateReportDataView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsInstructorOrAdmin]

    def get(self, request, report_slug: str, format=None):
        tenant = request.tenant
        report_query = Q(slug=report_slug, tenant=tenant) | Q(slug=report_slug, tenant__isnull=True)
        if not tenant: report_query = Q(slug=report_slug, tenant__isnull=True)
        try:
            report = Report.objects.get(report_query)
        except Report.DoesNotExist:
            return Response({"detail": f"Report '{report_slug}' not found."}, status=status.HTTP_404_NOT_FOUND)
        except Report.MultipleObjectsReturned:
             if tenant: report = Report.objects.get(slug=report_slug, tenant=tenant)
             else:
                 logger.error(f"Multiple system reports for slug {report_slug}")
                 return Response({"detail": "Configuration error."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        filters = {k: v for k, v in request.query_params.items() if k not in ['format']}
        
        # If user is an instructor (not admin), filter data to only their courses
        user = request.user
        if hasattr(user, 'role') and user.role == user.Role.INSTRUCTOR and not user.is_staff:
            # Add instructor filter to limit data to instructor's courses
            filters['instructor'] = user.id
        
        try:
            report_data_dict = ReportGeneratorService.generate_report_data(report, filters)
            serializer = ReportDataSerializer(report_data_dict) # Use serializer for consistent output
            return Response(serializer.data)
        except ReportGenerationError as e:
             return Response({"detail": f"Error generating report: {e}"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
             logger.error(f"Unexpected error generating report {report_slug}: {e}", exc_info=True)
             return Response({"detail": "Unexpected error."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    tags=['Analytics Data'],
    summary="Export Report Data",
    description="Generates report data and exports it as CSV or JSON.",
    parameters=[
        OpenApiParameter(name='report_slug', description='Slug of the report definition', required=True, type=OpenApiTypes.STR, location=OpenApiParameter.PATH, pattern=r'^[-\w]+$'),
        OpenApiParameter(name='format', description='Export format (csv or json)', required=True, type=OpenApiTypes.STR, enum=['csv', 'json'], location=OpenApiParameter.PATH),
        # Include filter parameters as in GenerateReportDataView
        OpenApiParameter(name='start_date', required=False, type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY),
        OpenApiParameter(name='end_date', required=False, type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY),
        OpenApiParameter(name='course_id', required=False, type=OpenApiTypes.UUID, location=OpenApiParameter.QUERY),
    ],
    responses={ 200: OpenApiResponse(description="File download"), 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT, 404: OpenApiTypes.OBJECT, 500: OpenApiTypes.OBJECT }
)
class ExportReportDataView(GenerateReportDataView):
    EXPORT_FORMATS = ['csv', 'json']

    def get(self, request, report_slug: str, format: str = 'csv', **kwargs):
        format_lower = format.lower()
        if format_lower not in self.EXPORT_FORMATS:
             return Response({"detail": f"Invalid export format '{format}'."}, status=status.HTTP_400_BAD_REQUEST)
        report_response = super().get(request, report_slug) # Calls parent GET
        if report_response.status_code != status.HTTP_200_OK: return report_response
        report_data_dict = report_response.data
        data_list = report_data_dict.get("data", [])
        if not data_list:
             return Response({"detail": "No data to export."}, status=status.HTTP_404_NOT_FOUND)
        timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
        filename_base = f"{report_slug}_{timestamp}"
        try:
            if format_lower == 'csv':
                content = ExportService.export_report_to_csv(data_list)
                response = HttpResponse(content, content_type='text/csv')
                response['Content-Disposition'] = f'attachment; filename="{filename_base}.csv"'
            elif format_lower == 'json':
                content = ExportService.export_report_to_json(data_list)
                response = HttpResponse(content, content_type='application/json')
                response['Content-Disposition'] = f'attachment; filename="{filename_base}.json"'
            return response
        except Exception as e:
             logger.error(f"Error exporting report {report_slug} as {format}: {e}", exc_info=True)
             return Response({"detail": "Error during export."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    tags=['Analytics Events'], summary="Track Event", request=EventSerializer,
    responses={201: OpenApiResponse(description="Event tracked (No content)")}
)
class TrackEventView(generics.CreateAPIView):
    serializer_class = EventSerializer
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        AnalyticsService.track_event(
            user=self.request.user, tenant=self.request.tenant,
            event_type=validated_data['event_type'],
            context_data=validated_data.get('context_data', {}), request=request
        )
        return Response(status=status.HTTP_201_CREATED)


@extend_schema(
    tags=['Instructor Analytics'],
    summary="Get Instructor Dashboard Analytics",
    description="Comprehensive analytics dashboard data for instructors including course performance, learner engagement, and assessment metrics.",
    parameters=[
        OpenApiParameter(name='course_id', description='Filter by specific course UUID', required=False, type=OpenApiTypes.UUID, location=OpenApiParameter.QUERY),
        OpenApiParameter(name='date_range', description='Time period (7d, 30d, 90d, 1y)', required=False, type=OpenApiTypes.STR, enum=['7d', '30d', '90d', '1y'], location=OpenApiParameter.QUERY),
        OpenApiParameter(name='start_date', description='Custom start date (YYYY-MM-DD)', required=False, type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY),
        OpenApiParameter(name='end_date', description='Custom end date (YYYY-MM-DD)', required=False, type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY),
    ],
    responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT}
)
class InstructorDashboardAnalyticsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsInstructorOrAdmin]
    
    def get(self, request, format=None):
        user = request.user
        tenant = request.tenant
        
        # Get query parameters
        course_id = request.query_params.get('course_id')
        date_range = request.query_params.get('date_range', '30d')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        
        try:
            # Get comprehensive dashboard data
            dashboard_data = AnalyticsService.get_instructor_dashboard_analytics(
                user=user,
                tenant=tenant,
                course_id=course_id,
                date_range=date_range,
                start_date=start_date,
                end_date=end_date
            )
            
            return Response(dashboard_data)
            
        except Exception as e:
            logger.error(f"Error getting instructor dashboard analytics: {e}", exc_info=True)
            return Response({"detail": "Error retrieving dashboard data."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    tags=['Instructor Analytics'],
    summary="Get Course Performance Analytics",
    description="Detailed performance analytics for specific courses including completion rates, assessment scores, and learner progress.",
    parameters=[
        OpenApiParameter(name='course_id', description='Course UUID', required=True, type=OpenApiTypes.UUID, location=OpenApiParameter.PATH),
        OpenApiParameter(name='date_range', description='Time period (7d, 30d, 90d, 1y)', required=False, type=OpenApiTypes.STR, enum=['7d', '30d', '90d', '1y'], location=OpenApiParameter.QUERY),
    ],
    responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT, 404: OpenApiTypes.OBJECT}
)
class CoursePerformanceAnalyticsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsInstructorOrAdmin]
    
    def get(self, request, course_id, format=None):
        user = request.user
        tenant = request.tenant
        date_range = request.query_params.get('date_range', '30d')
        
        try:
            # Verify instructor has access to this course
            from apps.courses.models import Course
            course = get_object_or_404(Course, id=course_id, tenant=tenant)
            
            # Check if user is instructor for this course or is admin
            if not user.is_staff and hasattr(user, 'role') and user.role == user.Role.INSTRUCTOR:
                if not course.instructors.filter(id=user.id).exists():
                    raise PermissionDenied("You don't have permission to view this course's analytics.")
            
            # Get course performance analytics
            performance_data = AnalyticsService.get_course_performance_analytics(
                course=course,
                user=user,
                tenant=tenant,
                date_range=date_range
            )
            
            return Response(performance_data)
            
        except Course.DoesNotExist:
            return Response({"detail": "Course not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error getting course performance analytics: {e}", exc_info=True)
            return Response({"detail": "Error retrieving performance data."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    tags=['Instructor Analytics'],
    summary="Get Learner Engagement Analytics",
    description="Detailed learner engagement metrics including activity patterns, session duration, and interaction frequency.",
    parameters=[
        OpenApiParameter(name='course_id', description='Filter by specific course UUID', required=False, type=OpenApiTypes.UUID, location=OpenApiParameter.QUERY),
        OpenApiParameter(name='learner_id', description='Filter by specific learner UUID', required=False, type=OpenApiTypes.UUID, location=OpenApiParameter.QUERY),
        OpenApiParameter(name='date_range', description='Time period (7d, 30d, 90d, 1y)', required=False, type=OpenApiTypes.STR, enum=['7d', '30d', '90d', '1y'], location=OpenApiParameter.QUERY),
    ],
    responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT}
)
class LearnerEngagementAnalyticsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsInstructorOrAdmin]
    
    def get(self, request, format=None):
        user = request.user
        tenant = request.tenant
        
        # Get query parameters
        course_id = request.query_params.get('course_id')
        learner_id = request.query_params.get('learner_id')
        date_range = request.query_params.get('date_range', '30d')
        
        try:
            # Get learner engagement analytics
            engagement_data = AnalyticsService.get_learner_engagement_analytics(
                user=user,
                tenant=tenant,
                course_id=course_id,
                learner_id=learner_id,
                date_range=date_range
            )
            
            return Response(engagement_data)
            
        except Exception as e:
            logger.error(f"Error getting learner engagement analytics: {e}", exc_info=True)
            return Response({"detail": "Error retrieving engagement data."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    tags=['Instructor Analytics'],
    summary="Get Assessment Analytics",
    description="Comprehensive assessment performance analytics including score distributions, question analysis, and completion rates.",
    parameters=[
        OpenApiParameter(name='course_id', description='Filter by specific course UUID', required=False, type=OpenApiTypes.UUID, location=OpenApiParameter.QUERY),
        OpenApiParameter(name='assessment_id', description='Filter by specific assessment UUID', required=False, type=OpenApiTypes.UUID, location=OpenApiParameter.QUERY),
        OpenApiParameter(name='date_range', description='Time period (7d, 30d, 90d, 1y)', required=False, type=OpenApiTypes.STR, enum=['7d', '30d', '90d', '1y'], location=OpenApiParameter.QUERY),
    ],
    responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT}
)
class AssessmentAnalyticsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsInstructorOrAdmin]
    
    def get(self, request, format=None):
        user = request.user
        tenant = request.tenant
        
        # Get query parameters
        course_id = request.query_params.get('course_id')
        assessment_id = request.query_params.get('assessment_id')
        date_range = request.query_params.get('date_range', '30d')
        
        try:
            # Get assessment analytics
            assessment_data = AnalyticsService.get_assessment_analytics(
                user=user,
                tenant=tenant,
                course_id=course_id,
                assessment_id=assessment_id,
                date_range=date_range
            )
            
            return Response(assessment_data)
            
        except Exception as e:
            logger.error(f"Error getting assessment analytics: {e}", exc_info=True)
            return Response({"detail": "Error retrieving assessment data."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    tags=['Instructor Analytics'],
    summary="Get Learning Progress Analytics",
    description="Detailed learning progress analytics including module completion, time spent, and learning path progression.",
    parameters=[
        OpenApiParameter(name='course_id', description='Filter by specific course UUID', required=False, type=OpenApiTypes.UUID, location=OpenApiParameter.QUERY),
        OpenApiParameter(name='learner_id', description='Filter by specific learner UUID', required=False, type=OpenApiTypes.UUID, location=OpenApiParameter.QUERY),
        OpenApiParameter(name='date_range', description='Time period (7d, 30d, 90d, 1y)', required=False, type=OpenApiTypes.STR, enum=['7d', '30d', '90d', '1y'], location=OpenApiParameter.QUERY),
    ],
    responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT}
)
class LearningProgressAnalyticsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsInstructorOrAdmin]
    
    def get(self, request, format=None):
        user = request.user
        tenant = request.tenant
        
        # Get query parameters
        course_id = request.query_params.get('course_id')
        learner_id = request.query_params.get('learner_id')
        date_range = request.query_params.get('date_range', '30d')
        
        try:
            # Get learning progress analytics
            progress_data = AnalyticsService.get_learning_progress_analytics(
                user=user,
                tenant=tenant,
                course_id=course_id,
                learner_id=learner_id,
                date_range=date_range
            )
            
            return Response(progress_data)
            
        except Exception as e:
            logger.error(f"Error getting learning progress analytics: {e}", exc_info=True)
            return Response({"detail": "Error retrieving progress data."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    tags=['Instructor Analytics'],
    summary="Get Real-time Activity Analytics",
    description="Real-time activity monitoring including active learners, current sessions, and live engagement metrics.",
    parameters=[
        OpenApiParameter(name='course_id', description='Filter by specific course UUID', required=False, type=OpenApiTypes.UUID, location=OpenApiParameter.QUERY),
    ],
    responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT}
)
class RealTimeActivityAnalyticsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsInstructorOrAdmin]
    
    def get(self, request, format=None):
        user = request.user
        tenant = request.tenant
        course_id = request.query_params.get('course_id')
        
        try:
            # Get real-time activity analytics
            activity_data = AnalyticsService.get_real_time_activity_analytics(
                user=user,
                tenant=tenant,
                course_id=course_id
            )
            
            return Response(activity_data)
            
        except Exception as e:
            logger.error(f"Error getting real-time activity analytics: {e}", exc_info=True)
            return Response({"detail": "Error retrieving activity data."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    tags=['Instructor Analytics'],
    summary="Get Comparative Analytics",
    description="Comparative analytics across courses, time periods, and cohorts including benchmarking and trend analysis.",
    parameters=[
        OpenApiParameter(name='comparison_type', description='Type of comparison (courses, time_periods, cohorts)', required=True, type=OpenApiTypes.STR, enum=['courses', 'time_periods', 'cohorts'], location=OpenApiParameter.QUERY),
        OpenApiParameter(name='course_ids', description='Comma-separated course UUIDs for comparison', required=False, type=OpenApiTypes.STR, location=OpenApiParameter.QUERY),
        OpenApiParameter(name='date_range', description='Time period (7d, 30d, 90d, 1y)', required=False, type=OpenApiTypes.STR, enum=['7d', '30d', '90d', '1y'], location=OpenApiParameter.QUERY),
    ],
    responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT}
)
class ComparativeAnalyticsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsInstructorOrAdmin]
    
    def get(self, request, format=None):
        user = request.user
        tenant = request.tenant
        
        # Get query parameters
        comparison_type = request.query_params.get('comparison_type')
        course_ids = request.query_params.get('course_ids')
        date_range = request.query_params.get('date_range', '30d')
        
        if not comparison_type:
            return Response({"detail": "comparison_type parameter is required."}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Parse course IDs if provided
            course_id_list = None
            if course_ids:
                course_id_list = [id.strip() for id in course_ids.split(',') if id.strip()]
            
            # Get comparative analytics
            comparative_data = AnalyticsService.get_comparative_analytics(
                user=user,
                tenant=tenant,
                comparison_type=comparison_type,
                course_ids=course_id_list,
                date_range=date_range
            )
            
            return Response(comparative_data)
            
        except Exception as e:
            logger.error(f"Error getting comparative analytics: {e}", exc_info=True)
            return Response({"detail": "Error retrieving comparative data."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    tags=['Instructor Analytics'],
    summary="Get Learning Content Analytics",
    description="Analytics for learning content including module completion rates, time spent per content type, and content effectiveness.",
    parameters=[
        OpenApiParameter(name='course_id', description='Filter by specific course UUID', required=False, type=OpenApiTypes.UUID, location=OpenApiParameter.QUERY),
        OpenApiParameter(name='content_type', description='Filter by content type (video, document, quiz, etc.)', required=False, type=OpenApiTypes.STR, location=OpenApiParameter.QUERY),
        OpenApiParameter(name='date_range', description='Time period (7d, 30d, 90d, 1y)', required=False, type=OpenApiTypes.STR, enum=['7d', '30d', '90d', '1y'], location=OpenApiParameter.QUERY),
    ],
    responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT}
)
class LearningContentAnalyticsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsInstructorOrAdmin]
    
    def get(self, request, format=None):
        user = request.user
        tenant = request.tenant
        
        # Get query parameters
        course_id = request.query_params.get('course_id')
        content_type = request.query_params.get('content_type')
        date_range = request.query_params.get('date_range', '30d')
        
        try:
            # Get learning content analytics
            content_data = AnalyticsService.get_learning_content_analytics(
                user=user,
                tenant=tenant,
                course_id=course_id,
                content_type=content_type,
                date_range=date_range
            )
            
            return Response(content_data)
            
        except Exception as e:
            logger.error(f"Error getting learning content analytics: {e}", exc_info=True)
            return Response({"detail": "Error retrieving content analytics."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
