from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_nested import routers
from .viewsets import InstructorAssessmentViewSet, QuestionViewSet

app_name = "instructor_assessments_api"

router = DefaultRouter()
router.register(r'assessments', InstructorAssessmentViewSet, basename='instructor-assessments')

# Add nested router for questions within instructor assessments
# /api/v1/instructor/assessments/{assessment_pk}/questions/
instructor_assessments_router = routers.NestedDefaultRouter(
    router, r'assessments', lookup='assessment'
)
instructor_assessments_router.register(
    r'questions', QuestionViewSet, basename='instructor-assessment-questions'
)

urlpatterns = [
    path('', include(router.urls)),
    path('', include(instructor_assessments_router.urls)),
]