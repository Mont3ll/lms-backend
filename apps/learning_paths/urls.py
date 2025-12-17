from django.urls import include, path
from rest_framework_nested import routers

from .viewsets import (
    LearningPathViewSet,
    LearningPathProgressViewSet,
    LearningPathStepProgressViewSet,
    PersonalizedLearningPathViewSet,
    PersonalizedPathProgressViewSet,
)

app_name = "learning_paths"

router = routers.DefaultRouter()
# Curated learning paths
router.register(r"learning-paths", LearningPathViewSet, basename="learningpath")
router.register(r"progress", LearningPathProgressViewSet, basename="learningpathprogress")
router.register(r"step-progress", LearningPathStepProgressViewSet, basename="learningpathstepprogress")

# Personalized learning paths
router.register(
    r"personalized-paths",
    PersonalizedLearningPathViewSet,
    basename="personalizedlearningpath"
)
router.register(
    r"personalized-progress",
    PersonalizedPathProgressViewSet,
    basename="personalizedpathprogress"
)

urlpatterns = [
    path("", include(router.urls)),
]
