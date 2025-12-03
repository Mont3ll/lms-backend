from django.urls import path
from apps.core.views import LearnerDashboardStatsView

app_name = "learner_core_api"

urlpatterns = [
    path('dashboard-stats/', LearnerDashboardStatsView.as_view(), name='learner-dashboard-stats'),
]