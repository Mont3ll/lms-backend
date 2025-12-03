from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .viewsets import ReportDefinitionViewSet, DashboardDefinitionViewSet, AnalyticsTrackingView, InstructorAnalyticsView

app_name = 'analytics_admin_api'

router = DefaultRouter()
router.register(r'report-definitions', ReportDefinitionViewSet, basename='report-definition')
router.register(r'dashboard-definitions', DashboardDefinitionViewSet, basename='dashboard-definition')

urlpatterns = [
    path('', include(router.urls)),
    path('instructor-analytics/', InstructorAnalyticsView.as_view(), name='instructor-analytics'),
    path('track/', AnalyticsTrackingView.as_view(), name='analytics-track'),
]