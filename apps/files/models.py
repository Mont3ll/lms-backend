import os
import uuid

from django.core.files.storage import (
    default_storage,
)  # To interact with configured storage
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import TimestampedModel
from apps.core.models import Tenant
from apps.users.models import User


def tenant_user_directory_path(instance, filename):
    """
    Generates a path like: tenants/{tenant_id}/users/{user_id}/files/{filename}
    Or adjust based on desired organization (e.g., by course, date).
    """
    tenant_id = (
        instance.tenant.id if instance.tenant else "public"
    )  # Handle files not tied to tenant?
    user_id = instance.uploaded_by.id if instance.uploaded_by else "system"
    # Sanitize filename if necessary
    _, extension = os.path.splitext(filename)
    # Use instance UUID for unique filename to avoid collisions and obscure original name
    safe_filename = f"{instance.id}{extension}"
    return f"tenants/{tenant_id}/users/{user_id}/{safe_filename}"


class Folder(TimestampedModel):
    """Represents a folder for organizing files within a tenant."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="folders")
    name = models.CharField(max_length=255)
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="subfolders",
    )
    # owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='owned_folders') # Optional ownership

    def __str__(self):
        if self.parent:
            return f"{self.parent} > {self.name}"
        return f"{self.name} ({self.tenant.name})"

    class Meta:
        unique_together = (
            "tenant",
            "parent",
            "name",
        )  # Folder names unique within parent/tenant
        ordering = ["tenant__name", "name"]


class File(TimestampedModel):
    """Represents an uploaded file."""

    class FileStatus(models.TextChoices):
        PENDING = "PENDING", _("Pending Upload")
        UPLOADING = "UPLOADING", _("Uploading")
        PROCESSING = "PROCESSING", _("Processing")  # e.g., scanning, thumbnailing
        AVAILABLE = "AVAILABLE", _("Available")
        ERROR = "ERROR", _("Error")
        DELETED = "DELETED", _("Deleted")  # Soft delete

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="files")
    folder = models.ForeignKey(
        Folder, on_delete=models.SET_NULL, null=True, blank=True, related_name="files"
    )  # Optional folder association
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_files",
    )

    # File field itself - uses configured storage backend (e.g., S3, local)
    file = models.FileField(upload_to=tenant_user_directory_path, max_length=1024)

    original_filename = models.CharField(
        max_length=255, help_text="Original name of the file when uploaded"
    )
    file_size = models.BigIntegerField(null=True, blank=True, help_text="Size in bytes")
    mime_type = models.CharField(
        max_length=255, blank=True, help_text="Detected MIME type"
    )
    status = models.CharField(
        max_length=20,
        choices=FileStatus.choices,
        default=FileStatus.PENDING,
        db_index=True,
    )
    error_message = models.TextField(
        blank=True, null=True, help_text="Details if status is ERROR"
    )

    # Metadata from processing
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Extracted metadata (e.g., image dimensions, video duration)",
    )
    scan_result = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Result from security scan (e.g., CLEAN, INFECTED)",
    )
    scan_details = models.TextField(blank=True, null=True)
    scan_completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.original_filename

    @property
    def file_url(self):
        """Returns the public or signed URL for accessing the file."""
        if self.file and hasattr(self.file, "url"):
            # For S3, default_storage.url() might generate a pre-signed URL if configured,
            # otherwise it returns the standard public URL.
            try:
                return default_storage.url(self.file.name)
            except Exception as e:
                # Handle cases where URL generation might fail
                print(f"Error generating URL for {self.file.name}: {e}")  # Log properly
                return None
        return None

    def save(self, *args, **kwargs):
        # Populate size/name before initial save if file exists? Or after upload complete?
        # This often happens in the service layer after upload.
        if self.file and not self.file_size:
            try:
                self.file_size = self.file.size
            except Exception:
                pass  # Handle case where size isn't available yet
        if self.file and not self.original_filename:
            self.original_filename = os.path.basename(
                self.file.name
            )  # Get name from storage path initially

        super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        # Override delete to remove the file from storage as well
        # Be careful with cascading deletes and versions
        file_path = self.file.name if self.file else None
        super().delete(using=using, keep_parents=keep_parents)  # Delete DB record first
        if file_path and default_storage.exists(file_path):
            try:
                default_storage.delete(file_path)
                print(f"Deleted file from storage: {file_path}")  # Log properly
            except Exception as e:
                print(
                    f"Error deleting file from storage {file_path}: {e}"
                )  # Log properly

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("File")
        verbose_name_plural = _("Files")


class FileVersion(TimestampedModel):
    """Tracks versions of a File (optional, if needed beyond ContentItem versioning)."""

    file_instance = models.ForeignKey(
        File, related_name="versions", on_delete=models.CASCADE
    )
    # Store reference to the actual file path in storage at this version
    # This implies files aren't overwritten in storage but saved with versioned names
    # Or, relies on storage backend's versioning (like S3 versioning)
    storage_path = models.CharField(max_length=1024)
    version_number = models.PositiveIntegerField(default=1)
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="User who created this version",
    )
    comment = models.TextField(blank=True)
    file_size = models.BigIntegerField(null=True, blank=True)
    mime_type = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.file_instance.original_filename} - v{self.version_number}"

    @property
    def version_url(self):
        """Returns URL for this specific version's file path."""
        try:
            return default_storage.url(self.storage_path)
        except Exception:
            return None

    class Meta:
        ordering = ["file_instance", "-version_number"]
        unique_together = ("file_instance", "version_number")
        verbose_name = _("File Version")
        verbose_name_plural = _("File Versions")


# StorageProvider model might be useful if supporting multiple backends dynamically,
# but often storage is configured globally via settings.
# class StorageProvider(TimestampedModel):
#     name = models.CharField(max_length=100, unique=True) # e.g., 'AWS S3 Public', 'MinIO Private'
#     provider_type = models.CharField(max_length=50) # e.g., 's3', 'local'
#     config = models.JSONField(default=dict, help_text="Provider specific config (bucket, keys, etc.)")
#     is_default = models.BooleanField(default=False)
