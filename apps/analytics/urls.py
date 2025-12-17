from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_nested import routers as nested_routers

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
    DashboardWidgetViewSet,
    WidgetDataView,
    WidgetMetaView,
    InstructorAnalyticsView,
    AdminAnalyticsView,
    StudentPerformanceViewSet,
    EngagementMetricsViewSet,
    AssessmentAnalyticsViewSet,
    AnalyticsTrackingView,
    EventLogViewSet,
    LearnerInsightsView,
)

app_name = "analytics"

router = DefaultRouter()
router.register(r"report-definitions", ReportDefinitionViewSet, basename="report-definition")
router.register(r"dashboards", DashboardDefinitionViewSet, basename="dashboard")
router.register(r"student-performance", StudentPerformanceViewSet, basename="student-performance")
router.register(r"engagement-metrics", EngagementMetricsViewSet, basename="engagement-metrics")
router.register(r"assessment-analytics", AssessmentAnalyticsViewSet, basename="assessment-analytics")
router.register(r"event-logs", EventLogViewSet, basename="event-log")

# Nested router for widgets under dashboards
dashboard_router = nested_routers.NestedDefaultRouter(router, r"dashboards", lookup="dashboard")
dashboard_router.register(r"widgets", DashboardWidgetViewSet, basename="dashboard-widget")

# Legacy router for backward compatibility
legacy_router = DefaultRouter()
legacy_router.register(r"report-definitions", ReportViewSet, basename="legacy-report-definition")
legacy_router.register(r"dashboard-definitions", DashboardViewSet, basename="legacy-dashboard-definition")

urlpatterns = [
    # Main instructor analytics endpoint (matches frontend API call)
    path("instructor/analytics/", InstructorAnalyticsView.as_view(), name="instructor-analytics"),
    
    # Admin analytics endpoint for platform-wide analytics
    path("admin/analytics/", AdminAnalyticsView.as_view(), name="admin-analytics"),
    
    # Learner insights endpoint for personalized learner analytics
    path("learner/insights/", LearnerInsightsView.as_view(), name="learner-insights"),
    
    # Analytics tracking
    path("track/", AnalyticsTrackingView.as_view(), name="analytics-tracking"),
    
    # Widget data endpoint - fetch data for a specific widget
    path("api/widgets/<uuid:widget_id>/data/", WidgetDataView.as_view(), name="widget-data"),
    
    # Widget metadata endpoint - list available widget types and data sources
    path("api/widgets/meta/", WidgetMetaView.as_view(), name="widget-meta"),
    
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
    
    # Include nested dashboard widgets router
    path("api/", include(dashboard_router.urls)),
    
    # Include legacy router URLs for backward compatibility
    path("legacy/", include(legacy_router.urls)),
    
    # Legacy dashboard-definitions path for backward compatibility
    path("api/dashboard-definitions/", DashboardDefinitionViewSet.as_view({'get': 'list'}), name="dashboard-definition-list"),
    path("api/dashboard-definitions/<uuid:pk>/", DashboardDefinitionViewSet.as_view({'get': 'retrieve'}), name="dashboard-definition-detail"),
]
