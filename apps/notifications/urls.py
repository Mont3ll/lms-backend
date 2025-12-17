from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AnnouncementViewSet, NotificationPreferenceView, NotificationViewSet, UserDeviceViewSet

app_name = "notifications"

router = DefaultRouter()
router.register(
    r"notifications", NotificationViewSet, basename="notification"
)  # Listing/reading user's notifications
router.register(
    r"devices", UserDeviceViewSet, basename="device"
)  # Device registration for push notifications
router.register(
    r"announcements", AnnouncementViewSet, basename="announcement"
)  # Admin announcements

urlpatterns = [
    path(
        "preferences/",
        NotificationPreferenceView.as_view(),
        name="notification-preferences",
    ),
    path("", include(router.urls)),
]
