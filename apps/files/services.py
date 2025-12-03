import logging
import mimetypes
import uuid

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.utils import timezone

from .models import File, Folder, Tenant, User

logger = logging.getLogger(__name__)


class FileUploadError(Exception):
    pass


class StorageService:
    """Service for handling file uploads, retrieval, and management."""

    @staticmethod
    def upload_file(
        *,
        uploaded_file: UploadedFile,
        tenant: Tenant,
        uploaded_by: User,
        folder: Folder | None = None,
    ) -> File:
        """
        Handles the process of uploading a file and creating the File record.
        """
        if not uploaded_file:
            raise ValueError("No file provided for upload.")
        if not tenant:
            raise ValueError("Tenant context is required for upload.")

        # Create initial File record in PENDING state
        db_file = File(
            tenant=tenant,
            folder=folder,
            uploaded_by=uploaded_by,
            original_filename=uploaded_file.name,
            file_size=uploaded_file.size,
            mime_type=uploaded_file.content_type
            or mimetypes.guess_type(uploaded_file.name)[0]
            or "application/octet-stream",
            status=File.FileStatus.PENDING,
        )
        # Save to get an ID, needed for the upload path function
        db_file.save()

        try:
            db_file.status = File.FileStatus.UPLOADING
            db_file.save(update_fields=["status"])

            # Assign the file content to the FileField - this triggers storage upload
            db_file.file.save(
                uploaded_file.name, uploaded_file, save=False
            )  # Use save=False initially

            # Update status after potential storage interaction (might be async later)
            # In a production system, upload might go direct to S3 (presigned URL),
            # and a webhook/callback updates the status.
            # For simple sync upload:
            db_file.status = (
                File.FileStatus.PROCESSING
            )  # Move to processing (scan, transform)
            db_file.save(update_fields=["file", "status"])

            logger.info(
                f"File {db_file.id} ({db_file.original_filename}) uploaded by {uploaded_by.id} for tenant {tenant.id}"
            )

            # Trigger async tasks for scanning and transformation
            # ScanningService.scan_file_task.delay(db_file.id)
            # TransformationService.transform_file_task.delay(db_file.id)

            return db_file

        except Exception as e:
            logger.error(
                f"Error uploading file {db_file.id} ({db_file.original_filename}): {e}",
                exc_info=True,
            )
            db_file.status = File.FileStatus.ERROR
            db_file.error_message = f"Upload failed: {e}"
            db_file.save(update_fields=["status", "error_message"])
            # Optionally, try to delete the partially uploaded file from storage here
            if db_file.file and default_storage.exists(db_file.file.name):
                try:
                    default_storage.delete(db_file.file.name)
                except Exception as del_e:
                    logger.error(
                        f"Failed to clean up storage for failed upload {db_file.id}: {del_e}"
                    )
            raise FileUploadError(f"Failed to upload file: {e}") from e

    @staticmethod
    def get_file_url(file_instance: File, expires_in: int = 3600) -> str | None:
        """
        Generates a potentially pre-signed URL for accessing a file.
        Requires storage backend (like S3Boto3Storage) configured for pre-signing.
        """
        if file_instance.status != File.FileStatus.AVAILABLE:
            logger.warning(
                f"Attempted to get URL for non-available file: {file_instance.id} (status: {file_instance.status})"
            )
            return None
        try:
            # url method in S3Boto3Storage accepts expire parameter
            return default_storage.url(file_instance.file.name, expire=expires_in)
        except Exception as e:
            logger.error(
                f"Error generating URL for file {file_instance.id}: {e}", exc_info=True
            )
            return None  # Fallback or return public URL if applicable and safe

    @staticmethod
    def delete_file(file_instance: File):
        """Deletes the file record and the file from storage."""
        logger.info(
            f"Deleting file {file_instance.id} ({file_instance.original_filename})"
        )
        # The delete override on the model handles storage deletion
        file_instance.delete()


class ScanningService:
    """Service for scanning files for threats. (Placeholder)"""

    @staticmethod
    def scan_file(file_id: uuid.UUID):
        """
        Scans the file using an external service or library (e.g., ClamAV).
        Updates the File model with results.
        """
        try:
            file_instance = File.objects.get(pk=file_id)
        except File.DoesNotExist:
            logger.error(f"Scan task: File {file_id} not found.")
            return

        if file_instance.status not in [
            File.FileStatus.PROCESSING,
            File.FileStatus.AVAILABLE,
        ]:  # Rescan?
            logger.info(
                f"Scan task: Skipping file {file_id} with status {file_instance.status}"
            )
            return

        logger.info(f"Scanning file {file_id} ({file_instance.original_filename})...")
        # --- Integration with actual scanner ---
        # Example: scan_result, details = clamav_scanner.scan(file_instance.file.path) # If local
        # Example: response = requests.post(SCANNER_API_URL, files={'file': file_instance.file.open()})
        # Dummy result:
        scan_result_code = "CLEAN"  # or "INFECTED"
        scan_details_text = "Scan completed successfully."
        # ---------------------------------------

        file_instance.scan_result = scan_result_code
        file_instance.scan_details = scan_details_text
        file_instance.scan_completed_at = timezone.now()

        # Update status based on scan result and other processing
        if scan_result_code == "INFECTED":
            file_instance.status = File.FileStatus.ERROR
            file_instance.error_message = "File scan detected a potential threat."
            logger.warning(f"File {file_id} scan result: INFECTED")
            # Optionally delete the infected file from storage here? Requires careful policy.
        elif file_instance.status == File.FileStatus.PROCESSING:
            # If no other processing needed, mark as available
            # Check if transformation is done? Assume done for now.
            file_instance.status = File.FileStatus.AVAILABLE
            logger.info(f"File {file_id} scan result: CLEAN. Marked as AVAILABLE.")

        file_instance.save(
            update_fields=[
                "scan_result",
                "scan_details",
                "scan_completed_at",
                "status",
                "error_message",
            ]
        )

    @staticmethod
    def scan_file_task(file_id: uuid.UUID):
        """Celery task wrapper for scanning."""
        # Implement as Celery task
        logger.info(f"Received scan task for file: {file_id}")
        ScanningService.scan_file(file_id)


class TransformationService:
    """Service for file transformations like image resizing, document conversion. (Placeholder)"""

    @staticmethod
    def transform_file(file_id: uuid.UUID):
        """
        Performs necessary transformations based on file type and context.
        (e.g., generate thumbnails for images, convert documents to PDF).
        Updates File metadata.
        """
        try:
            file_instance = File.objects.get(pk=file_id)
        except File.DoesNotExist:
            logger.error(f"Transform task: File {file_id} not found.")
            return

        logger.info(
            f"Transforming file {file_id} ({file_instance.original_filename})..."
        )
        mime = file_instance.mime_type

        try:
            if mime and mime.startswith("image/"):
                # Example: Generate thumbnail
                # thumbnail_path = generate_thumbnail(file_instance.file.path) # Use Pillow
                # Save thumbnail to storage
                # Update file_instance.metadata['thumbnail_url'] = storage.url(thumbnail_path)
                pass
            elif mime and mime in [
                "application/pdf",
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ]:
                # Example: Convert document to preview format (e.g., images of pages)
                # preview_paths = generate_document_preview(file_instance.file.path) # Use LibreOffice/unoconv
                # Update file_instance.metadata['previews'] = [...]
                pass
            # Add other transformations (video encoding, etc.)

            # Update status if processing is complete
            if file_instance.status == File.FileStatus.PROCESSING:
                # Check if scanning is also done? Assume done for now.
                file_instance.status = File.FileStatus.AVAILABLE
                logger.info(
                    f"File {file_id} transformation complete. Marked as AVAILABLE."
                )

        except Exception as e:
            logger.error(f"Error transforming file {file_id}: {e}", exc_info=True)
            file_instance.status = File.FileStatus.ERROR
            file_instance.error_message = f"Transformation failed: {e}"

        file_instance.save()

    @staticmethod
    def transform_file_task(file_id: uuid.UUID):
        """Celery task wrapper for transformation."""
        # Implement as Celery task
        logger.info(f"Received transform task for file: {file_id}")
        TransformationService.transform_file(file_id)
