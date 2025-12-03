from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .viewsets import LearnerGroupViewSet, UserViewSet

app_name = "users_api"

router = DefaultRouter()
router.register(
    r"manage", UserViewSet, basename="user-manage"
)  # e.g., /api/v1/users/manage/
router.register(
    r"groups", LearnerGroupViewSet, basename="learnergroup"
)  # e.g., /api/v1/users/groups/

urlpatterns = [
    path("", include(router.urls)),
]
