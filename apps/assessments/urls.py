from django.urls import include, path
from rest_framework_nested import routers

from .views import (
    AssessmentAttemptResultView,
    StartAssessmentAttemptView,
    SubmitAssessmentAttemptView,
)
from .viewsets import AssessmentViewSet, QuestionViewSet

app_name = "assessments"

router = routers.DefaultRouter()
router.register(r"", AssessmentViewSet, basename="assessment")

# Nested router for questions within an assessment
# /api/v1/assessments/{assessment_pk}/questions/
assessments_router = routers.NestedDefaultRouter(
    router, r"", lookup="assessment"
)
assessments_router.register(
    r"questions", QuestionViewSet, basename="assessment-question"
)

urlpatterns = [
    path("", include(router.urls)),
    path("", include(assessments_router.urls)),
    # Attempt specific URLs
    path(
        "<uuid:assessment_id>/start/",
        StartAssessmentAttemptView.as_view(),
        name="assessment-attempt-start",
    ),
    path(
        "attempts/<uuid:attempt_id>/submit/",
        SubmitAssessmentAttemptView.as_view(),
        name="assessment-attempt-submit",
    ),
    path(
        "attempts/<uuid:id>/result/",
        AssessmentAttemptResultView.as_view(),
        name="assessment-attempt-result",
    ),  # Use 'id' to match lookup_field
]
