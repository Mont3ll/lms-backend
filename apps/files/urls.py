from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    FileUploadView,
    FileViewSet,
    FileVersionDetailView,
    FileVersionListView,
    FileVersionRestoreView,
    FileThumbnailView,
    FolderViewSet,
)

app_name = "files"

router = DefaultRouter()
router.register(r"files", FileViewSet, basename="file")
router.register(r"folders", FolderViewSet, basename="folder")

urlpatterns = [
    path("upload/", FileUploadView.as_view(), name="file-upload"),
    # File versioning endpoints
    path(
        "files/<uuid:file_pk>/versions/",
        FileVersionListView.as_view(),
        name="file-version-list",
    ),
    path(
        "files/<uuid:file_pk>/versions/<int:version_number>/",
        FileVersionDetailView.as_view(),
        name="file-version-detail",
    ),
    path(
        "files/<uuid:file_pk>/versions/<int:version_number>/restore/",
        FileVersionRestoreView.as_view(),
        name="file-version-restore",
    ),
    # Thumbnail endpoints
    path(
        "files/<uuid:file_pk>/thumbnails/",
        FileThumbnailView.as_view(),
        name="file-thumbnails",
    ),
    path("", include(router.urls)),  # File and Folder management
]
