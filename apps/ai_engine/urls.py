from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    GeneratedContentViewSet,
    GenerationJobViewSet,
    ModelConfigViewSet,
    ModuleRecommendationsView,
    ModuleSequenceView,
    PromptTemplateViewSet,
    SkillGapAnalysisView,
    StartGenerationJobView,
)

app_name = "ai_engine"

router = DefaultRouter()
router.register(r"jobs", GenerationJobViewSet, basename="generationjob")
router.register(
    r"generated-content", GeneratedContentViewSet, basename="generatedcontent"
)
router.register(r"model-configs", ModelConfigViewSet, basename="modelconfig")
router.register(r"prompt-templates", PromptTemplateViewSet, basename="prompttemplate")

urlpatterns = [
    path("generate/", StartGenerationJobView.as_view(), name="start-generation"),
    # Module recommendation endpoints
    path("recommendations/modules/", ModuleRecommendationsView.as_view(), name="module-recommendations"),
    path("recommendations/sequence/", ModuleSequenceView.as_view(), name="module-sequence"),
    path("recommendations/skill-gaps/", SkillGapAnalysisView.as_view(), name="skill-gap-analysis"),
    path("", include(router.urls)),
]
