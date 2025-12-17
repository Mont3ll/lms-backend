from django.urls import path
from apps.core.views import LearnerDashboardStatsView, LearnerRecommendationsView

app_name = "learner_core_api"

urlpatterns = [
    path('dashboard-stats/', LearnerDashboardStatsView.as_view(), name='learner-dashboard-stats'),
    path('recommendations/', LearnerRecommendationsView.as_view(), name='learner-recommendations'),
]