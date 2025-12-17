import logging
import mimetypes
import uuid
from typing import Tuple

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import UploadedFile
from django.utils import timezone

from .models import File, FileVersion, Folder, Tenant, User

logger = logging.getLogger(__name__)


def get_versioned_storage_path(file_instance: File, version_number: int) -> str:
    """
    Generate a storage path for a specific file version.
    Format: tenants/{tenant_id}/users/{user_id}/versions/{file_id}_v{version}.{ext}
    """
    import os
    tenant_id = file_instance.tenant.id if file_instance.tenant else "public"
    user_id = file_instance.uploaded_by.id if file_instance.uploaded_by else "system"
    _, extension = os.path.splitext(file_instance.original_filename)
    return f"tenants/{tenant_id}/users/{user_id}/versions/{file_instance.id}_v{version_number}{extension}"


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
            from .tasks import scan_file_task, transform_file_task
            scan_file_task.delay(str(db_file.id))
            transform_file_task.delay(str(db_file.id))

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
    def create_version(
        *,
        file_instance: File,
        uploaded_file: UploadedFile,
        user: User,
        comment: str = "",
    ) -> FileVersion:
        """
        Creates a new version of an existing file.
        
        This saves the current file content as a version before updating the main file,
        or saves the uploaded file directly as a new version.
        
        Args:
            file_instance: The File object to version
            uploaded_file: The new file content to upload
            user: User creating the version
            comment: Optional comment about this version
            
        Returns:
            The created FileVersion object
        """
        from django.db import transaction
        
        if file_instance.status not in [File.FileStatus.AVAILABLE, File.FileStatus.PROCESSING]:
            raise FileUploadError(
                f"Cannot create version for file with status: {file_instance.status}"
            )
        
        with transaction.atomic():
            # Determine next version number
            latest_version = file_instance.versions.order_by("-version_number").first()
            next_version_number = (latest_version.version_number + 1) if latest_version else 1
            
            # If this is the first version, preserve the original file first
            if next_version_number == 1 and file_instance.file:
                original_version_path = get_versioned_storage_path(file_instance, 1)
                
                # Copy current file to version storage
                try:
                    with default_storage.open(file_instance.file.name, 'rb') as original:
                        default_storage.save(original_version_path, original)
                except Exception as e:
                    logger.error(f"Failed to save original version: {e}")
                    raise FileUploadError(f"Failed to save original version: {e}")
                
                # Create version record for original
                FileVersion.objects.create(
                    file_instance=file_instance,
                    version_number=1,
                    storage_path=original_version_path,
                    file_size=file_instance.file_size,
                    mime_type=file_instance.mime_type,
                    user=file_instance.uploaded_by,
                    comment="Original version",
                )
                next_version_number = 2
            
            # Generate path for new version
            new_version_path = get_versioned_storage_path(file_instance, next_version_number)
            
            # Save new version file to storage
            mime_type = (
                uploaded_file.content_type 
                or mimetypes.guess_type(uploaded_file.name)[0] 
                or "application/octet-stream"
            )
            
            try:
                default_storage.save(new_version_path, uploaded_file)
            except Exception as e:
                logger.error(f"Failed to save new version to storage: {e}")
                raise FileUploadError(f"Failed to save version file: {e}")
            
            # Create version record
            version = FileVersion.objects.create(
                file_instance=file_instance,
                version_number=next_version_number,
                storage_path=new_version_path,
                file_size=uploaded_file.size,
                mime_type=mime_type,
                user=user,
                comment=comment,
            )
            
            # Update main file with new version content
            # Reset file position for re-read
            uploaded_file.seek(0)
            
            # Delete old main file
            old_file_name = file_instance.file.name if file_instance.file else None
            
            # Save new content to main file path
            file_instance.file.save(uploaded_file.name, uploaded_file, save=False)
            file_instance.file_size = uploaded_file.size
            file_instance.mime_type = mime_type
            file_instance.save(update_fields=["file", "file_size", "mime_type", "updated_at"])
            
            # Clean up old main file if it exists and is different
            if old_file_name and old_file_name != file_instance.file.name:
                try:
                    if default_storage.exists(old_file_name):
                        default_storage.delete(old_file_name)
                except Exception as e:
                    logger.warning(f"Failed to clean up old file {old_file_name}: {e}")
            
            logger.info(
                f"Created version {next_version_number} for file {file_instance.id} "
                f"by user {user.id}"
            )
            
            return version

    @staticmethod
    def list_versions(file_instance: File) -> list[FileVersion]:
        """
        Returns all versions of a file, ordered by version number descending.
        """
        return list(
            file_instance.versions.select_related("user").order_by("-version_number")
        )

    @staticmethod
    def get_version(file_instance: File, version_number: int) -> FileVersion | None:
        """
        Get a specific version of a file.
        """
        try:
            return file_instance.versions.select_related("user").get(
                version_number=version_number
            )
        except FileVersion.DoesNotExist:
            return None

    @staticmethod
    def get_version_url(version: FileVersion, expires_in: int = 3600) -> str | None:
        """
        Generates a potentially pre-signed URL for accessing a specific file version.
        """
        try:
            return default_storage.url(version.storage_path, expire=expires_in)
        except Exception as e:
            logger.error(
                f"Error generating URL for version {version.id}: {e}", exc_info=True
            )
            return None

    @staticmethod
    def restore_version(
        file_instance: File, version_number: int, user: User
    ) -> FileVersion:
        """
        Restores a file to a previous version by creating a new version
        with the content from the specified version.
        
        Args:
            file_instance: The File object
            version_number: The version number to restore
            user: User performing the restore
            
        Returns:
            The newly created version (copy of the restored version)
        """
        version_to_restore = StorageService.get_version(file_instance, version_number)
        if not version_to_restore:
            raise FileUploadError(f"Version {version_number} not found")
        
        # Read the version file content
        try:
            with default_storage.open(version_to_restore.storage_path, 'rb') as f:
                from django.core.files.base import ContentFile
                content = ContentFile(f.read(), name=file_instance.original_filename)
        except Exception as e:
            logger.error(f"Failed to read version {version_number}: {e}")
            raise FileUploadError(f"Failed to read version content: {e}")
        
        # Create new version with restored content
        return StorageService.create_version(
            file_instance=file_instance,
            uploaded_file=content,
            user=user,
            comment=f"Restored from version {version_number}",
        )

    @staticmethod
    def delete_version(file_instance: File, version_number: int) -> bool:
        """
        Deletes a specific version of a file.
        Cannot delete the only remaining version or the current (latest) version.
        
        Args:
            file_instance: The File object
            version_number: The version number to delete
            
        Returns:
            True if deleted successfully
        """
        version_count = file_instance.versions.count()
        
        if version_count <= 1:
            raise FileUploadError("Cannot delete the only remaining version")
        
        latest_version = file_instance.versions.order_by("-version_number").first()
        if latest_version and latest_version.version_number == version_number:
            raise FileUploadError("Cannot delete the latest version. Restore an older version first.")
        
        try:
            version = file_instance.versions.get(version_number=version_number)
        except FileVersion.DoesNotExist:
            raise FileUploadError(f"Version {version_number} not found")
        
        # Delete from storage
        if version.storage_path and default_storage.exists(version.storage_path):
            try:
                default_storage.delete(version.storage_path)
            except Exception as e:
                logger.warning(f"Failed to delete version file from storage: {e}")
        
        # Delete record
        version.delete()
        logger.info(f"Deleted version {version_number} of file {file_instance.id}")
        
        return True

    @staticmethod
    def delete_file(file_instance: File):
        """Deletes the file record and the file from storage."""
        logger.info(
            f"Deleting file {file_instance.id} ({file_instance.original_filename})"
        )
        # The delete override on the model handles storage deletion
        file_instance.delete()


class ScanningService:
    """Service for scanning files for threats using ClamAV."""

    _clamd_connection = None

    @classmethod
    def get_clamd_connection(cls):
        """
        Get or create a connection to the ClamAV daemon.
        Returns None if ClamAV is not enabled or unavailable.
        """
        if not getattr(settings, 'CLAMAV_ENABLED', False):
            return None

        if cls._clamd_connection is not None:
            # Test if connection is still alive
            try:
                cls._clamd_connection.ping()
                return cls._clamd_connection
            except Exception:
                cls._clamd_connection = None

        try:
            import pyclamd
            
            connection_type = getattr(settings, 'CLAMAV_CONNECTION_TYPE', 'tcp')
            
            if connection_type == 'socket':
                socket_path = getattr(settings, 'CLAMAV_SOCKET', '/var/run/clamav/clamd.ctl')
                cls._clamd_connection = pyclamd.ClamdUnixSocket(filename=socket_path)
            else:  # tcp
                host = getattr(settings, 'CLAMAV_HOST', 'localhost')
                port = getattr(settings, 'CLAMAV_PORT', 3310)
                cls._clamd_connection = pyclamd.ClamdNetworkSocket(host=host, port=port)
            
            # Test connection
            if cls._clamd_connection.ping():
                logger.info(f"ClamAV connection established ({connection_type})")
                return cls._clamd_connection
            else:
                logger.error("ClamAV daemon is not responding")
                cls._clamd_connection = None
                return None
                
        except ImportError:
            logger.error("pyclamd library is not installed. Run: poetry add pyclamd")
            return None
        except Exception as e:
            logger.error(f"Failed to connect to ClamAV: {e}")
            cls._clamd_connection = None
            return None

    @staticmethod
    def scan_stream(file_content: bytes) -> Tuple[str, str]:
        """
        Scan file content using ClamAV stream scanning.
        
        Returns:
            Tuple of (result_code, details):
            - ("CLEAN", "No threats detected")
            - ("INFECTED", "Virus name: <name>")
            - ("ERROR", "Error message")
            - ("SKIPPED", "Reason for skipping")
        """
        clamd = ScanningService.get_clamd_connection()
        
        if clamd is None:
            if not getattr(settings, 'CLAMAV_ENABLED', False):
                return ("SKIPPED", "ClamAV scanning is disabled")
            return ("ERROR", "ClamAV daemon is not available")
        
        # Check file size limit
        max_size = getattr(settings, 'CLAMAV_MAX_FILE_SIZE', 100 * 1024 * 1024)
        if len(file_content) > max_size:
            return ("SKIPPED", f"File exceeds maximum scan size ({max_size} bytes)")
        
        try:
            # pyclamd.scan_stream returns:
            # - None if clean
            # - {'stream': ('FOUND', 'VirusName')} if infected
            import io
            result = clamd.scan_stream(io.BytesIO(file_content))
            
            if result is None:
                return ("CLEAN", "No threats detected")
            
            # Extract virus info from result
            if 'stream' in result:
                status, virus_name = result['stream']
                if status == 'FOUND':
                    return ("INFECTED", f"Threat detected: {virus_name}")
            
            return ("CLEAN", "No threats detected")
            
        except Exception as e:
            logger.error(f"ClamAV scan error: {e}", exc_info=True)
            return ("ERROR", f"Scan failed: {str(e)}")

    @staticmethod
    def scan_file(file_id: uuid.UUID):
        """
        Scans the file using ClamAV.
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
        ]:
            logger.info(
                f"Scan task: Skipping file {file_id} with status {file_instance.status}"
            )
            return

        logger.info(f"Scanning file {file_id} ({file_instance.original_filename})...")
        
        try:
            # Read file content from storage
            if file_instance.file and file_instance.file.name:
                with default_storage.open(file_instance.file.name, 'rb') as f:
                    file_content = f.read()
                
                # Perform the scan
                scan_result_code, scan_details_text = ScanningService.scan_stream(file_content)
            else:
                scan_result_code = "ERROR"
                scan_details_text = "File content not available for scanning"
                
        except Exception as e:
            logger.error(f"Error reading file {file_id} for scanning: {e}", exc_info=True)
            scan_result_code = "ERROR"
            scan_details_text = f"Failed to read file for scanning: {str(e)}"

        file_instance.scan_result = scan_result_code
        file_instance.scan_details = scan_details_text
        file_instance.scan_completed_at = timezone.now()

        # Update status based on scan result
        if scan_result_code == "INFECTED":
            file_instance.status = File.FileStatus.ERROR
            file_instance.error_message = f"File scan detected a potential threat: {scan_details_text}"
            logger.warning(f"File {file_id} scan result: INFECTED - {scan_details_text}")
            
            # Delete the infected file from storage for security
            if file_instance.file and default_storage.exists(file_instance.file.name):
                try:
                    default_storage.delete(file_instance.file.name)
                    logger.info(f"Deleted infected file {file_id} from storage")
                except Exception as del_e:
                    logger.error(f"Failed to delete infected file {file_id}: {del_e}")
                    
        elif scan_result_code == "ERROR":
            # Don't mark as error - allow manual review
            logger.warning(f"File {file_id} scan error: {scan_details_text}")
            # Keep in PROCESSING state for retry or manual review
            
        elif scan_result_code in ["CLEAN", "SKIPPED"]:
            # If no other processing needed, mark as available
            if file_instance.status == File.FileStatus.PROCESSING:
                file_instance.status = File.FileStatus.AVAILABLE
                logger.info(f"File {file_id} scan result: {scan_result_code}. Marked as AVAILABLE.")

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
        # This should be decorated with @celery_app.task in a tasks.py file
        logger.info(f"Received scan task for file: {file_id}")
        ScanningService.scan_file(file_id)


class TransformationService:
    """Service for file transformations like image resizing, document conversion."""

    # Thumbnail settings
    THUMBNAIL_SIZES = {
        'small': (150, 150),
        'medium': (300, 300),
        'large': (600, 600),
    }
    SUPPORTED_IMAGE_FORMATS = ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/bmp']

    @staticmethod
    def get_thumbnail_storage_path(file_instance: File, size_name: str) -> str:
        """
        Generate a storage path for a thumbnail.
        Format: tenants/{tenant_id}/thumbnails/{file_id}_{size}.jpg
        """
        tenant_id = file_instance.tenant.id if file_instance.tenant else "public"
        return f"tenants/{tenant_id}/thumbnails/{file_instance.id}_{size_name}.jpg"

    @staticmethod
    def generate_thumbnail(
        file_instance: File,
        size_name: str = 'medium',
        quality: int = 85,
    ) -> str | None:
        """
        Generate a thumbnail for an image file.
        
        Args:
            file_instance: The File object (must be an image)
            size_name: Thumbnail size ('small', 'medium', 'large')
            quality: JPEG quality (1-100)
            
        Returns:
            URL of the generated thumbnail, or None if generation fails
        """
        if file_instance.mime_type not in TransformationService.SUPPORTED_IMAGE_FORMATS:
            logger.warning(
                f"Cannot generate thumbnail for non-image file: {file_instance.id} "
                f"(mime: {file_instance.mime_type})"
            )
            return None
        
        if size_name not in TransformationService.THUMBNAIL_SIZES:
            logger.warning(f"Invalid thumbnail size: {size_name}")
            size_name = 'medium'
        
        target_size = TransformationService.THUMBNAIL_SIZES[size_name]
        
        try:
            from PIL import Image
            import io
            
            # Read original image from storage
            with default_storage.open(file_instance.file.name, 'rb') as f:
                original_image = Image.open(f)
                
                # Handle RGBA images (convert to RGB for JPEG)
                if original_image.mode in ('RGBA', 'P'):
                    # Create white background
                    background = Image.new('RGB', original_image.size, (255, 255, 255))
                    if original_image.mode == 'P':
                        original_image = original_image.convert('RGBA')
                    background.paste(original_image, mask=original_image.split()[-1])
                    original_image = background
                elif original_image.mode != 'RGB':
                    original_image = original_image.convert('RGB')
                
                # Create thumbnail (maintains aspect ratio)
                original_image.thumbnail(target_size, Image.Resampling.LANCZOS)
                
                # Save to buffer
                buffer = io.BytesIO()
                original_image.save(buffer, format='JPEG', quality=quality, optimize=True)
                buffer.seek(0)
                
                # Generate storage path
                thumbnail_path = TransformationService.get_thumbnail_storage_path(
                    file_instance, size_name
                )
                
                # Delete existing thumbnail if present
                if default_storage.exists(thumbnail_path):
                    default_storage.delete(thumbnail_path)
                
                # Save thumbnail to storage
                from django.core.files.base import ContentFile
                default_storage.save(thumbnail_path, ContentFile(buffer.read()))
                
                logger.info(
                    f"Generated {size_name} thumbnail for file {file_instance.id}: {thumbnail_path}"
                )
                
                return thumbnail_path
                
        except ImportError:
            logger.error(
                "Pillow library is not installed. Run: poetry add Pillow"
            )
            return None
        except Exception as e:
            logger.error(
                f"Error generating thumbnail for file {file_instance.id}: {e}",
                exc_info=True
            )
            return None

    @staticmethod
    def generate_all_thumbnails(file_instance: File) -> dict[str, str | None]:
        """
        Generate all thumbnail sizes for an image file.
        
        Returns:
            Dictionary mapping size names to their storage paths/URLs
        """
        thumbnails = {}
        
        if file_instance.mime_type not in TransformationService.SUPPORTED_IMAGE_FORMATS:
            return thumbnails
        
        for size_name in TransformationService.THUMBNAIL_SIZES.keys():
            path = TransformationService.generate_thumbnail(file_instance, size_name)
            if path:
                try:
                    thumbnails[size_name] = default_storage.url(path)
                except Exception:
                    thumbnails[size_name] = path
        
        return thumbnails

    @staticmethod
    def get_thumbnail_url(
        file_instance: File,
        size_name: str = 'medium',
        expires_in: int = 3600,
    ) -> str | None:
        """
        Get the URL for an existing thumbnail.
        
        Args:
            file_instance: The File object
            size_name: Thumbnail size name
            expires_in: URL expiration in seconds (for signed URLs)
            
        Returns:
            Thumbnail URL or None if not found
        """
        thumbnail_path = TransformationService.get_thumbnail_storage_path(
            file_instance, size_name
        )
        
        if not default_storage.exists(thumbnail_path):
            return None
        
        try:
            return default_storage.url(thumbnail_path, expire=expires_in)
        except Exception as e:
            logger.error(f"Error getting thumbnail URL: {e}")
            return None

    @staticmethod
    def delete_thumbnails(file_instance: File) -> None:
        """Delete all thumbnails for a file."""
        for size_name in TransformationService.THUMBNAIL_SIZES.keys():
            thumbnail_path = TransformationService.get_thumbnail_storage_path(
                file_instance, size_name
            )
            if default_storage.exists(thumbnail_path):
                try:
                    default_storage.delete(thumbnail_path)
                    logger.info(f"Deleted thumbnail: {thumbnail_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete thumbnail {thumbnail_path}: {e}")

    @staticmethod
    def extract_image_metadata(file_instance: File) -> dict:
        """
        Extract metadata from an image file.
        
        Returns:
            Dictionary with width, height, format, and other metadata
        """
        metadata = {}
        
        if file_instance.mime_type not in TransformationService.SUPPORTED_IMAGE_FORMATS:
            return metadata
        
        try:
            from PIL import Image
            from PIL.ExifTags import TAGS
            
            with default_storage.open(file_instance.file.name, 'rb') as f:
                img = Image.open(f)
                
                metadata['width'] = img.width
                metadata['height'] = img.height
                metadata['format'] = img.format
                metadata['mode'] = img.mode
                
                # Extract EXIF data if available
                exif_data = {}
                if hasattr(img, '_getexif') and img._getexif():
                    for tag_id, value in img._getexif().items():
                        tag = TAGS.get(tag_id, tag_id)
                        # Skip binary data
                        if isinstance(value, bytes):
                            continue
                        exif_data[tag] = str(value)
                
                if exif_data:
                    metadata['exif'] = exif_data
                    
        except ImportError:
            logger.warning("Pillow not installed, cannot extract image metadata")
        except Exception as e:
            logger.warning(f"Failed to extract image metadata: {e}")
        
        return metadata

    @staticmethod
    def transform_file(file_id: uuid.UUID):
        """
        Performs necessary transformations based on file type and context.
        (e.g., generate thumbnails for images, extract metadata).
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
        metadata = file_instance.metadata or {}

        try:
            if mime and mime in TransformationService.SUPPORTED_IMAGE_FORMATS:
                # Generate thumbnails for images
                thumbnails = TransformationService.generate_all_thumbnails(file_instance)
                if thumbnails:
                    metadata['thumbnails'] = thumbnails
                
                # Extract image metadata
                image_meta = TransformationService.extract_image_metadata(file_instance)
                if image_meta:
                    metadata.update(image_meta)
                
                logger.info(f"Generated thumbnails and metadata for image {file_id}")
                
            elif mime and mime in [
                "application/pdf",
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ]:
                # Document preview generation can be added here
                # Would require additional dependencies like pdf2image, LibreOffice
                logger.info(f"Document transformation not yet implemented for {file_id}")
                pass
            
            # Add other transformations (video encoding, etc.)

            # Update metadata
            file_instance.metadata = metadata
            
            # Update status if processing is complete
            if file_instance.status == File.FileStatus.PROCESSING:
                # Only mark as AVAILABLE if scan is also complete or skipped
                if file_instance.scan_result in ['CLEAN', 'SKIPPED', None]:
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
