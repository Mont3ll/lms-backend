from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    DashboardViewSet,
    ExportReportDataView,
    GenerateReportDataView,
    ReportViewSet,
    TrackEventView,
)

from .viewsets import (
    ReportDefinitionViewSet,
    DashboardDefinitionViewSet,
    InstructorAnalyticsView,
    StudentPerformanceViewSet,
    EngagementMetricsViewSet,
    AssessmentAnalyticsViewSet,
    AnalyticsTrackingView,
)

app_name = "analytics"

router = DefaultRouter()
router.register(r"report-definitions", ReportDefinitionViewSet, basename="report-definition")
router.register(r"dashboard-definitions", DashboardDefinitionViewSet, basename="dashboard-definition")
router.register(r"student-performance", StudentPerformanceViewSet, basename="student-performance")
router.register(r"engagement-metrics", EngagementMetricsViewSet, basename="engagement-metrics")
router.register(r"assessment-analytics", AssessmentAnalyticsViewSet, basename="assessment-analytics")

# Legacy router for backward compatibility
legacy_router = DefaultRouter()
legacy_router.register(r"report-definitions", ReportViewSet, basename="legacy-report-definition")
legacy_router.register(r"dashboard-definitions", DashboardViewSet, basename="legacy-dashboard-definition")

urlpatterns = [
    # Main instructor analytics endpoint (matches frontend API call)
    path("instructor/analytics/", InstructorAnalyticsView.as_view(), name="instructor-analytics"),
    
    # Analytics tracking
    path("track/", AnalyticsTrackingView.as_view(), name="analytics-tracking"),
    
    # Report Data Generation & Export (legacy)
    path(
        "reports/<slug:report_slug>/data/",
        GenerateReportDataView.as_view(),
        name="generate-report-data",
    ),
    path(
        "reports/<slug:report_slug>/export/<str:format>/",
        ExportReportDataView.as_view(),
        name="export-report-data",
    ),
    path(
        "reports/<slug:report_slug>/export/",
        ExportReportDataView.as_view(),
        {"format": "csv"},
        name="export-report-data-csv",
    ),
    
    # Event Tracking (legacy)
    path("track-legacy/", TrackEventView.as_view(), name="track-event-legacy"),
    
    # Include comprehensive analytics router URLs
    path("api/", include(router.urls)),
    
    # Include legacy router URLs for backward compatibility
    path("legacy/", include(legacy_router.urls)),
]
