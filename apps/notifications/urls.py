from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import NotificationPreferenceView, NotificationViewSet

app_name = "notifications"

router = DefaultRouter()
router.register(
    r"notifications", NotificationViewSet, basename="notification"
)  # Listing/reading user's notifications

urlpatterns = [
    path(
        "preferences/",
        NotificationPreferenceView.as_view(),
        name="notification-preferences",
    ),
    path("", include(router.urls)),
]
