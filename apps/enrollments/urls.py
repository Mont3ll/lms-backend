from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CertificateViewSet,
    CreateEnrollmentView,
    CreateGroupEnrollmentView,
    EnrollmentViewSet,
    LearnerProgressListView,
    UpdateLearnerProgressView,
)
from .enrollment_status_view import EnrollmentStatusView
from .self_enrollment_view import SelfEnrollmentView

app_name = "enrollments"

router = DefaultRouter()
router.register(
    r"enrollments", EnrollmentViewSet, basename="enrollment"
)  # Read-only listing
router.register(
    r"certificates", CertificateViewSet, basename="certificate"
)  # Read-only listing

urlpatterns = [
    # Enrollment Management (Admin/Instructor)
    path(
        "enrollments/create/", CreateEnrollmentView.as_view(), name="enrollment-create"
    ),
    path(
        "group-enrollments/create/",
        CreateGroupEnrollmentView.as_view(),
        name="group-enrollment-create",
    ),
    # Learner Progress Tracking
    path(
        "enrollments/<uuid:enrollment_id>/progress/",
        LearnerProgressListView.as_view(),
        name="learner-progress-list",
    ),
    path(
        "enrollments/<uuid:enrollment_id>/progress/<uuid:content_item_id>/",
        UpdateLearnerProgressView.as_view(),
        name="learner-progress-update",
    ),
    # Enrollment Status Check
    path(
        "enrollment-status/<slug:course_slug>/",
        EnrollmentStatusView.as_view(),
        name="enrollment-status",
    ),
    # Self Enrollment
    path(
        "enroll/",
        SelfEnrollmentView.as_view(),
        name="self-enroll",
    ),
    # Include router URLs for listing
    path("", include(router.urls)),
]
