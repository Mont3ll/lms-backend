from django.urls import path
from apps.core.views import InstructorDashboardStatsView, InstructorReportsView
from apps.analytics.viewsets import InstructorAnalyticsView

urlpatterns = [
    path('dashboard-stats/', InstructorDashboardStatsView.as_view(), name='instructor-dashboard-stats'),
    path('reports/', InstructorReportsView.as_view(), name='instructor-reports'),
    path('analytics/', InstructorAnalyticsView.as_view(), name='instructor-analytics'),
]