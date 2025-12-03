from django.urls import include, path
from rest_framework_nested import routers

from .viewsets import LearningPathViewSet, LearningPathProgressViewSet, LearningPathStepProgressViewSet

app_name = "learning_paths"

router = routers.DefaultRouter()
router.register(r"learning-paths", LearningPathViewSet, basename="learningpath")
router.register(r"progress", LearningPathProgressViewSet, basename="learningpathprogress")
router.register(r"step-progress", LearningPathStepProgressViewSet, basename="learningpathstepprogress")

urlpatterns = [
    path("", include(router.urls)),
]
