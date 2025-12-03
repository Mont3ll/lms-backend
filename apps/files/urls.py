from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import FileDetailView, FileUploadView, FolderViewSet

app_name = "files"

router = DefaultRouter()
router.register(r"folders", FolderViewSet, basename="folder")

urlpatterns = [
    path("upload/", FileUploadView.as_view(), name="file-upload"),
    path(
        "files/<uuid:pk>/", FileDetailView.as_view(), name="file-detail"
    ),  # Retrieve/Delete file record
    path("", include(router.urls)),  # Folder management
]
