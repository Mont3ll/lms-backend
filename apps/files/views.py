import logging
import uuid
from rest_framework import generics, permissions, status, parsers, viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import File, FileVersion, Folder, Tenant
from .serializers import (
    FileSerializer,
    FileVersionSerializer,
    FileVersionUploadSerializer,
    FolderSerializer,
    FileUploadSerializer,
)
from .services import StorageService, FileUploadError, TransformationService
from apps.users.permissions import IsAdminOrTenantAdmin
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

logger = logging.getLogger(__name__)

@extend_schema(
    tags=['Files'],
    summary="Upload File",
    description="Uploads a file, typically associating it with the current user and tenant. Use multipart/form-data.",
    request={'multipart/form-data': FileUploadSerializer}, # Document request body
    responses={201: FileSerializer, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT}
)
class FileUploadView(APIView):
    """ Handles direct file uploads. """
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]
    permission_classes = [permissions.IsAuthenticated] # Allow any authenticated user

    def post(self, request, format=None):
        # Pass request to context for serializer validation
        upload_serializer = FileUploadSerializer(data=request.data, context={'request': request})
        if upload_serializer.is_valid():
            uploaded_file = upload_serializer.validated_data['file']
            folder_id = upload_serializer.validated_data.get('folder_id')
            folder = None
            tenant = request.tenant # Get tenant from middleware

            # Folder instance fetched based on validated ID
            if folder_id:
                try:
                    # Re-verify folder belongs to tenant for safety
                    folder = Folder.objects.get(pk=folder_id, tenant=tenant)
                except Folder.DoesNotExist:
                     # Serializer should have caught this, but double-check
                     return Response({"detail": "Specified folder not found."}, status=status.HTTP_404_NOT_FOUND)

            if not tenant: # Should be caught by middleware/permissions usually
                return Response({"detail": "Tenant context is required for file upload."}, status=status.HTTP_400_BAD_REQUEST)

            try:
                db_file = StorageService.upload_file(
                    uploaded_file=uploaded_file,
                    tenant=tenant,
                    uploaded_by=request.user,
                    folder=folder
                )
                # Return info using the standard FileSerializer
                file_info_serializer = FileSerializer(db_file, context={'request': request})
                return Response(file_info_serializer.data, status=status.HTTP_201_CREATED)
            except FileUploadError as e:
                 logger.error(f"File Upload Service Error: {e}", exc_info=True)
                 return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            except ValueError as e: # Catch validation errors from service
                 return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e: # Catch unexpected errors
                 logger.error(f"Unexpected error during file upload: {e}", exc_info=True)
                 return Response({"detail": "An unexpected error occurred during upload."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        else:
            return Response(upload_serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(tags=['Files'])
class FileViewSet(viewsets.ModelViewSet):
    """API endpoint for listing, retrieving, and deleting files within a tenant."""
    serializer_class = FileSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ['get', 'delete', 'head', 'options']  # Disable PUT/POST/PATCH

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='folder_id',
                description='Filter by folder UUID. Use "root" or omit for files without a folder.',
                required=False,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY
            ),
            OpenApiParameter(
                name='status',
                description='Filter by file status (e.g., AVAILABLE, PENDING)',
                required=False,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY
            ),
            OpenApiParameter(
                name='search',
                description='Search files by original filename',
                required=False,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return File.objects.none()

        user = self.request.user
        tenant = self.request.tenant

        if not user.is_authenticated:
            return File.objects.none()

        # Base queryset - filter by tenant
        if user.is_superuser:
            queryset = File.objects.all()
            # Allow superuser to filter by tenant if needed
            tenant_id_filter = self.request.query_params.get('tenant_id')
            if tenant_id_filter:
                queryset = queryset.filter(tenant_id=tenant_id_filter)
        elif tenant:
            queryset = File.objects.filter(tenant=tenant)
        else:
            return File.objects.none()

        # Filter by folder
        folder_filter = self.request.query_params.get('folder_id')
        if folder_filter == 'root':
            queryset = queryset.filter(folder__isnull=True)
        elif folder_filter:
            try:
                folder_uuid = uuid.UUID(folder_filter)
                queryset = queryset.filter(folder_id=folder_uuid)
            except ValueError:
                queryset = File.objects.none()

        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        # Search by filename
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(original_filename__icontains=search)

        return queryset.select_related('tenant', 'folder', 'uploaded_by').order_by('-created_at')

    def retrieve(self, request, *args, **kwargs):
        """Retrieve file details including a download URL."""
        instance = self.get_object()
        signed_url = StorageService.get_file_url(instance)
        serializer = self.get_serializer(instance)
        data = serializer.data
        data['download_url'] = signed_url
        return Response(data)

    def destroy(self, request, *args, **kwargs):
        """Delete a file. Only uploader or admin can delete."""
        instance = self.get_object()
        user = request.user
        
        # Only allow deletion by uploader or admin/superuser
        is_uploader = instance.uploaded_by == user
        is_admin = user.is_staff or user.is_superuser
        
        if not (is_uploader or is_admin):
            return Response(
                {"detail": "You do not have permission to delete this file."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=['Files'],
    summary="Retrieve/Delete File",
    description="Retrieve file details (including a temporary download URL) or delete a file record and its storage.",
    parameters=[OpenApiParameter(name='pk', description='File UUID', required=True, type=OpenApiTypes.UUID, location=OpenApiParameter.PATH)],
    responses={
        200: OpenApiResponse(response=FileSerializer, description="File details with download_url"),
        204: OpenApiResponse(description="File deleted successfully"),
        403: OpenApiTypes.OBJECT, 404: OpenApiTypes.OBJECT
    }
)
class FileDetailView(generics.RetrieveDestroyAPIView):
    """ Retrieve or delete a specific file record. """
    serializer_class = FileSerializer
    permission_classes = [permissions.IsAuthenticated] # Object permissions checked below
    lookup_field = 'pk' # Default, using UUID primary key

    def get_queryset(self):
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return File.objects.none()

        user = self.request.user
        tenant = self.request.tenant

        if not user.is_authenticated: return File.objects.none()

        if user.is_superuser:
            return File.objects.all().select_related('tenant', 'folder', 'uploaded_by')
        elif tenant:
             # Users can generally only access files within their tenant
            return File.objects.filter(tenant=tenant).select_related('tenant', 'folder', 'uploaded_by')
        return File.objects.none()

    def check_object_permissions(self, request, obj):
        """ Check if user can access/delete this specific file. """
        super().check_object_permissions(request, obj) # Apply base permissions
        user = request.user
        # Allow retrieval by anyone in the tenant? Or only uploader/admins? Assume tenant access is enough for retrieve.
        if request.method == 'DELETE':
            # Only allow deletion by uploader or tenant admin/superuser
            is_uploader = obj.uploaded_by == user
            is_admin = user.is_staff # Assumes staff are admins (tenant or super)
            if not (is_uploader or is_admin):
                 self.permission_denied(request, message="You do not have permission to delete this file.")

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object() # Checks permissions via get_queryset & check_object_permissions
        # Generate a short-lived signed URL for retrieval if using private storage
        # The duration can be configured in settings or passed to service
        signed_url = StorageService.get_file_url(instance)
        serializer = self.get_serializer(instance)
        data = serializer.data
        # Add the potentially signed URL to the response
        data['download_url'] = signed_url
        return Response(data)

    # Destroy action uses model's delete method which handles storage cleanup


@extend_schema(tags=['Files'])
class FolderViewSet(viewsets.ModelViewSet):
    """ API endpoint for managing Folders within a tenant. """
    serializer_class = FolderSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrTenantAdmin] # Only admins manage folders? Or allow users? Assume Admin for now.

    # Add parameters for filtering documentation
    @extend_schema(
        parameters=[
            OpenApiParameter(name='parent', description='Filter by parent folder UUID, or "root" for top-level folders', required=False, type=OpenApiTypes.STR, location=OpenApiParameter.QUERY),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return Folder.objects.none()

        user = self.request.user
        tenant = self.request.tenant

        if not user.is_authenticated: return Folder.objects.none()

        # Base queryset
        if user.is_superuser:
             queryset = Folder.objects.all()
             # Allow superuser to filter by tenant if needed
             tenant_id_filter = self.request.query_params.get('tenant_id')
             if tenant_id_filter: queryset = queryset.filter(tenant_id=tenant_id_filter)
        elif tenant and user.is_staff: # Tenant Admin
             queryset = Folder.objects.filter(tenant=tenant)
        else: # Regular users cannot manage folders (based on current permissions)
             return Folder.objects.none()

        # Apply parent filter
        parent_filter = self.request.query_params.get('parent')
        if parent_filter == 'root':
             queryset = queryset.filter(parent__isnull=True)
        elif parent_filter:
             try:
                 parent_uuid = uuid.UUID(parent_filter)
                 queryset = queryset.filter(parent_id=parent_uuid)
             except ValueError:
                 queryset = Folder.objects.none() # Invalid parent UUID format

        return queryset.select_related('tenant', 'parent').order_by('name')

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request # Pass request for tenant validation in serializer
        return context

    def perform_create(self, serializer):
        # Tenant is set automatically in serializer based on request context
        serializer.save() # Serializer's create method handles tenant assignment

    # Add perform_update/destroy if needed, ensuring tenant consistency


# File Version Views

@extend_schema(tags=['File Versions'])
class FileVersionListView(generics.ListCreateAPIView):
    """
    List all versions of a file or create a new version.
    
    GET: Returns all versions of a file, ordered by version number descending.
    POST: Uploads a new version of the file.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return FileVersionUploadSerializer
        return FileVersionSerializer

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return FileVersion.objects.none()
        
        file_id = self.kwargs.get('file_pk')
        user = self.request.user
        tenant = self.request.tenant

        if not user.is_authenticated:
            return FileVersion.objects.none()

        # Get base file queryset based on permissions
        if user.is_superuser:
            file_qs = File.objects.all()
        elif tenant:
            file_qs = File.objects.filter(tenant=tenant)
        else:
            return FileVersion.objects.none()

        # Check file exists and user has access
        try:
            file_uuid = uuid.UUID(str(file_id))
            file_instance = file_qs.get(pk=file_uuid)
        except (ValueError, File.DoesNotExist):
            return FileVersion.objects.none()

        return FileVersion.objects.filter(file_instance=file_instance).select_related('user').order_by('-version_number')

    def get_file_instance(self):
        """Helper to get the file instance for the current request."""
        file_id = self.kwargs.get('file_pk')
        tenant = self.request.tenant
        user = self.request.user

        if user.is_superuser:
            file_qs = File.objects.all()
        elif tenant:
            file_qs = File.objects.filter(tenant=tenant)
        else:
            return None

        try:
            file_uuid = uuid.UUID(str(file_id))
            return file_qs.get(pk=file_uuid)
        except (ValueError, File.DoesNotExist):
            return None

    @extend_schema(
        summary="List file versions",
        description="Returns all versions of a file, ordered by version number descending.",
        responses={200: FileVersionSerializer(many=True)}
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        summary="Upload new file version",
        description="Uploads a new version of an existing file. The uploaded file becomes the new current version.",
        request={'multipart/form-data': FileVersionUploadSerializer},
        responses={
            201: FileVersionSerializer,
            400: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT
        }
    )
    def post(self, request, *args, **kwargs):
        file_instance = self.get_file_instance()
        if not file_instance:
            return Response(
                {"detail": "File not found or you don't have access."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Check if user can create versions (uploader or admin)
        is_uploader = file_instance.uploaded_by == request.user
        is_admin = request.user.is_staff or request.user.is_superuser
        if not (is_uploader or is_admin):
            return Response(
                {"detail": "You do not have permission to create versions for this file."},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = FileVersionUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            version = StorageService.create_version(
                file_instance=file_instance,
                uploaded_file=serializer.validated_data['file'],
                user=request.user,
                comment=serializer.validated_data.get('comment', ''),
            )
            return Response(
                FileVersionSerializer(version).data,
                status=status.HTTP_201_CREATED
            )
        except FileUploadError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error creating file version: {e}", exc_info=True)
            return Response(
                {"detail": "An unexpected error occurred."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@extend_schema(tags=['File Versions'])
class FileVersionDetailView(APIView):
    """
    Retrieve or delete a specific version of a file.
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [parsers.MultiPartParser, parsers.FormParser, parsers.JSONParser]

    def get_file_and_version(self, request, file_pk, version_number):
        """Helper to get file and version objects."""
        tenant = request.tenant
        user = request.user

        if user.is_superuser:
            file_qs = File.objects.all()
        elif tenant:
            file_qs = File.objects.filter(tenant=tenant)
        else:
            return None, None

        try:
            file_uuid = uuid.UUID(str(file_pk))
            file_instance = file_qs.get(pk=file_uuid)
        except (ValueError, File.DoesNotExist):
            return None, None

        version = StorageService.get_version(file_instance, version_number)
        return file_instance, version

    @extend_schema(
        summary="Get file version details",
        description="Returns details of a specific file version including a download URL.",
        parameters=[
            OpenApiParameter(name='file_pk', description='File UUID', required=True, type=OpenApiTypes.UUID, location=OpenApiParameter.PATH),
            OpenApiParameter(name='version_number', description='Version number', required=True, type=OpenApiTypes.INT, location=OpenApiParameter.PATH),
        ],
        responses={
            200: FileVersionSerializer,
            404: OpenApiTypes.OBJECT
        }
    )
    def get(self, request, file_pk, version_number):
        file_instance, version = self.get_file_and_version(request, file_pk, version_number)
        
        if not file_instance:
            return Response(
                {"detail": "File not found or you don't have access."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if not version:
            return Response(
                {"detail": f"Version {version_number} not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = FileVersionSerializer(version)
        data = serializer.data
        data['download_url'] = StorageService.get_version_url(version)
        return Response(data)

    @extend_schema(
        summary="Delete file version",
        description="Deletes a specific version. Cannot delete the only remaining version or the latest version.",
        parameters=[
            OpenApiParameter(name='file_pk', description='File UUID', required=True, type=OpenApiTypes.UUID, location=OpenApiParameter.PATH),
            OpenApiParameter(name='version_number', description='Version number', required=True, type=OpenApiTypes.INT, location=OpenApiParameter.PATH),
        ],
        responses={
            204: OpenApiResponse(description="Version deleted successfully"),
            400: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT
        }
    )
    def delete(self, request, file_pk, version_number):
        file_instance, version = self.get_file_and_version(request, file_pk, version_number)
        
        if not file_instance:
            return Response(
                {"detail": "File not found or you don't have access."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Check permissions (uploader or admin)
        is_uploader = file_instance.uploaded_by == request.user
        is_admin = request.user.is_staff or request.user.is_superuser
        if not (is_uploader or is_admin):
            return Response(
                {"detail": "You do not have permission to delete versions of this file."},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            StorageService.delete_version(file_instance, version_number)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except FileUploadError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error deleting file version: {e}", exc_info=True)
            return Response(
                {"detail": "An unexpected error occurred."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@extend_schema(tags=['File Versions'])
class FileVersionRestoreView(APIView):
    """
    Restore a file to a previous version.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Restore file version",
        description="Restores a file to a previous version by creating a new version with the content from the specified version.",
        parameters=[
            OpenApiParameter(name='file_pk', description='File UUID', required=True, type=OpenApiTypes.UUID, location=OpenApiParameter.PATH),
            OpenApiParameter(name='version_number', description='Version number to restore', required=True, type=OpenApiTypes.INT, location=OpenApiParameter.PATH),
        ],
        responses={
            201: FileVersionSerializer,
            400: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT
        }
    )
    def post(self, request, file_pk, version_number):
        tenant = request.tenant
        user = request.user

        if user.is_superuser:
            file_qs = File.objects.all()
        elif tenant:
            file_qs = File.objects.filter(tenant=tenant)
        else:
            return Response(
                {"detail": "Tenant context required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            file_uuid = uuid.UUID(str(file_pk))
            file_instance = file_qs.get(pk=file_uuid)
        except (ValueError, File.DoesNotExist):
            return Response(
                {"detail": "File not found or you don't have access."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Check permissions (uploader or admin)
        is_uploader = file_instance.uploaded_by == user
        is_admin = user.is_staff or user.is_superuser
        if not (is_uploader or is_admin):
            return Response(
                {"detail": "You do not have permission to restore versions of this file."},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            new_version = StorageService.restore_version(
                file_instance=file_instance,
                version_number=version_number,
                user=user
            )
            return Response(
                FileVersionSerializer(new_version).data,
                status=status.HTTP_201_CREATED
            )
        except FileUploadError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error restoring file version: {e}", exc_info=True)
            return Response(
                {"detail": "An unexpected error occurred."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# Thumbnail Views

@extend_schema(tags=['File Thumbnails'])
class FileThumbnailView(APIView):
    """
    Get or generate thumbnails for an image file.
    
    GET: Returns URLs for all available thumbnail sizes, generating them if needed.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_file_instance(self, request, file_pk):
        """Helper to get the file instance with proper permission checks."""
        tenant = request.tenant
        user = request.user

        if user.is_superuser:
            file_qs = File.objects.all()
        elif tenant:
            file_qs = File.objects.filter(tenant=tenant)
        else:
            return None

        try:
            file_uuid = uuid.UUID(str(file_pk))
            return file_qs.get(pk=file_uuid)
        except (ValueError, File.DoesNotExist):
            return None

    @extend_schema(
        summary="Get file thumbnails",
        description=(
            "Returns URLs for thumbnails of an image file. "
            "Available sizes: small (150x150), medium (300x300), large (600x600). "
            "Thumbnails are generated on first request if they don't exist."
        ),
        parameters=[
            OpenApiParameter(
                name='file_pk',
                description='File UUID',
                required=True,
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH
            ),
            OpenApiParameter(
                name='size',
                description='Specific size to return (small, medium, large). If omitted, returns all sizes.',
                required=False,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY
            ),
            OpenApiParameter(
                name='generate',
                description='If true, generates thumbnails if they do not exist (default: true)',
                required=False,
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY
            ),
        ],
        responses={
            200: OpenApiResponse(
                description="Thumbnail URLs",
                response={
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string", "format": "uuid"},
                        "thumbnails": {
                            "type": "object",
                            "properties": {
                                "small": {"type": "string", "format": "uri", "nullable": True},
                                "medium": {"type": "string", "format": "uri", "nullable": True},
                                "large": {"type": "string", "format": "uri", "nullable": True},
                            }
                        }
                    }
                }
            ),
            400: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT
        }
    )
    def get(self, request, file_pk):
        file_instance = self.get_file_instance(request, file_pk)
        
        if not file_instance:
            return Response(
                {"detail": "File not found or you don't have access."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if file is an image
        if file_instance.mime_type not in TransformationService.SUPPORTED_IMAGE_FORMATS:
            return Response(
                {"detail": f"Thumbnails not available for file type: {file_instance.mime_type}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if file is available
        if file_instance.status != File.FileStatus.AVAILABLE:
            return Response(
                {"detail": f"File is not available (status: {file_instance.status})"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get query params
        requested_size = request.query_params.get('size')
        should_generate = request.query_params.get('generate', 'true').lower() != 'false'
        
        # Validate size param if provided
        valid_sizes = list(TransformationService.THUMBNAIL_SIZES.keys())
        if requested_size and requested_size not in valid_sizes:
            return Response(
                {"detail": f"Invalid size. Valid sizes: {', '.join(valid_sizes)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        thumbnails = {}
        sizes_to_process = [requested_size] if requested_size else valid_sizes
        
        for size_name in sizes_to_process:
            # Try to get existing thumbnail URL
            url = TransformationService.get_thumbnail_url(file_instance, size_name)
            
            if url:
                thumbnails[size_name] = url
            elif should_generate:
                # Generate the thumbnail
                path = TransformationService.generate_thumbnail(file_instance, size_name)
                if path:
                    thumbnails[size_name] = TransformationService.get_thumbnail_url(
                        file_instance, size_name
                    )
                else:
                    thumbnails[size_name] = None
            else:
                thumbnails[size_name] = None
        
        return Response({
            "file_id": str(file_instance.id),
            "original_filename": file_instance.original_filename,
            "thumbnails": thumbnails,
        })

    @extend_schema(
        summary="Regenerate thumbnails",
        description="Force regeneration of thumbnails for an image file.",
        parameters=[
            OpenApiParameter(
                name='file_pk',
                description='File UUID',
                required=True,
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH
            ),
        ],
        responses={
            200: OpenApiResponse(description="Regenerated thumbnail URLs"),
            400: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT
        }
    )
    def post(self, request, file_pk):
        """Force regeneration of thumbnails."""
        file_instance = self.get_file_instance(request, file_pk)
        
        if not file_instance:
            return Response(
                {"detail": "File not found or you don't have access."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check permissions (uploader or admin)
        is_uploader = file_instance.uploaded_by == request.user
        is_admin = request.user.is_staff or request.user.is_superuser
        if not (is_uploader or is_admin):
            return Response(
                {"detail": "You do not have permission to regenerate thumbnails for this file."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if file is an image
        if file_instance.mime_type not in TransformationService.SUPPORTED_IMAGE_FORMATS:
            return Response(
                {"detail": f"Thumbnails not available for file type: {file_instance.mime_type}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if file is available
        if file_instance.status != File.FileStatus.AVAILABLE:
            return Response(
                {"detail": f"File is not available (status: {file_instance.status})"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Delete existing thumbnails
            TransformationService.delete_thumbnails(file_instance)
            
            # Generate new thumbnails
            thumbnails = TransformationService.generate_all_thumbnails(file_instance)
            
            return Response({
                "file_id": str(file_instance.id),
                "original_filename": file_instance.original_filename,
                "thumbnails": thumbnails,
                "message": "Thumbnails regenerated successfully",
            })
        except Exception as e:
            logger.error(f"Error regenerating thumbnails for file {file_pk}: {e}", exc_info=True)
            return Response(
                {"detail": "Failed to regenerate thumbnails."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        summary="Delete thumbnails",
        description="Delete all thumbnails for a file.",
        parameters=[
            OpenApiParameter(
                name='file_pk',
                description='File UUID',
                required=True,
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH
            ),
        ],
        responses={
            204: OpenApiResponse(description="Thumbnails deleted"),
            403: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT
        }
    )
    def delete(self, request, file_pk):
        """Delete all thumbnails for a file."""
        file_instance = self.get_file_instance(request, file_pk)
        
        if not file_instance:
            return Response(
                {"detail": "File not found or you don't have access."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check permissions (uploader or admin)
        is_uploader = file_instance.uploaded_by == request.user
        is_admin = request.user.is_staff or request.user.is_superuser
        if not (is_uploader or is_admin):
            return Response(
                {"detail": "You do not have permission to delete thumbnails for this file."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            TransformationService.delete_thumbnails(file_instance)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            logger.error(f"Error deleting thumbnails for file {file_pk}: {e}", exc_info=True)
            return Response(
                {"detail": "Failed to delete thumbnails."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# Thumbnail Views

@extend_schema(tags=['File Thumbnails'])
class FileThumbnailView(APIView):
    """
    Get or generate thumbnails for an image file.
    
    GET: Returns URLs for all available thumbnail sizes, generating them if needed.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_file_instance(self, request, file_pk):
        """Helper to get the file instance with proper permission checks."""
        tenant = request.tenant
        user = request.user

        if user.is_superuser:
            file_qs = File.objects.all()
        elif tenant:
            file_qs = File.objects.filter(tenant=tenant)
        else:
            return None

        try:
            file_uuid = uuid.UUID(str(file_pk))
            return file_qs.get(pk=file_uuid)
        except (ValueError, File.DoesNotExist):
            return None

    @extend_schema(
        summary="Get file thumbnails",
        description=(
            "Returns URLs for thumbnails of an image file. "
            "Available sizes: small (150x150), medium (300x300), large (600x600). "
            "Thumbnails are generated on first request if they don't exist."
        ),
        parameters=[
            OpenApiParameter(
                name='file_pk',
                description='File UUID',
                required=True,
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH
            ),
            OpenApiParameter(
                name='size',
                description='Specific size to return (small, medium, large). If omitted, returns all sizes.',
                required=False,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY
            ),
            OpenApiParameter(
                name='generate',
                description='If true, generates thumbnails if they do not exist (default: true)',
                required=False,
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY
            ),
        ],
        responses={
            200: OpenApiResponse(
                description="Thumbnail URLs",
                response={
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string", "format": "uuid"},
                        "thumbnails": {
                            "type": "object",
                            "properties": {
                                "small": {"type": "string", "format": "uri", "nullable": True},
                                "medium": {"type": "string", "format": "uri", "nullable": True},
                                "large": {"type": "string", "format": "uri", "nullable": True},
                            }
                        }
                    }
                }
            ),
            400: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT
        }
    )
    def get(self, request, file_pk):
        file_instance = self.get_file_instance(request, file_pk)
        
        if not file_instance:
            return Response(
                {"detail": "File not found or you don't have access."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if file is an image
        if file_instance.mime_type not in TransformationService.SUPPORTED_IMAGE_FORMATS:
            return Response(
                {"detail": f"Thumbnails not available for file type: {file_instance.mime_type}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if file is available
        if file_instance.status != File.FileStatus.AVAILABLE:
            return Response(
                {"detail": f"File is not available (status: {file_instance.status})"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get query params
        requested_size = request.query_params.get('size')
        should_generate = request.query_params.get('generate', 'true').lower() != 'false'
        
        # Validate size param if provided
        valid_sizes = list(TransformationService.THUMBNAIL_SIZES.keys())
        if requested_size and requested_size not in valid_sizes:
            return Response(
                {"detail": f"Invalid size. Valid sizes: {', '.join(valid_sizes)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        thumbnails = {}
        sizes_to_process = [requested_size] if requested_size else valid_sizes
        
        for size_name in sizes_to_process:
            # Try to get existing thumbnail URL
            url = TransformationService.get_thumbnail_url(file_instance, size_name)
            
            if url:
                thumbnails[size_name] = url
            elif should_generate:
                # Generate the thumbnail
                path = TransformationService.generate_thumbnail(file_instance, size_name)
                if path:
                    thumbnails[size_name] = TransformationService.get_thumbnail_url(
                        file_instance, size_name
                    )
                else:
                    thumbnails[size_name] = None
            else:
                thumbnails[size_name] = None
        
        return Response({
            "file_id": str(file_instance.id),
            "original_filename": file_instance.original_filename,
            "thumbnails": thumbnails,
        })

    @extend_schema(
        summary="Regenerate thumbnails",
        description="Force regeneration of thumbnails for an image file.",
        parameters=[
            OpenApiParameter(
                name='file_pk',
                description='File UUID',
                required=True,
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH
            ),
        ],
        responses={
            200: OpenApiResponse(description="Regenerated thumbnail URLs"),
            400: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT
        }
    )
    def post(self, request, file_pk):
        """Force regeneration of thumbnails."""
        file_instance = self.get_file_instance(request, file_pk)
        
        if not file_instance:
            return Response(
                {"detail": "File not found or you don't have access."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check permissions (uploader or admin)
        is_uploader = file_instance.uploaded_by == request.user
        is_admin = request.user.is_staff or request.user.is_superuser
        if not (is_uploader or is_admin):
            return Response(
                {"detail": "You do not have permission to regenerate thumbnails for this file."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if file is an image
        if file_instance.mime_type not in TransformationService.SUPPORTED_IMAGE_FORMATS:
            return Response(
                {"detail": f"Thumbnails not available for file type: {file_instance.mime_type}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if file is available
        if file_instance.status != File.FileStatus.AVAILABLE:
            return Response(
                {"detail": f"File is not available (status: {file_instance.status})"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Delete existing thumbnails
            TransformationService.delete_thumbnails(file_instance)
            
            # Generate new thumbnails
            thumbnails = TransformationService.generate_all_thumbnails(file_instance)
            
            return Response({
                "file_id": str(file_instance.id),
                "original_filename": file_instance.original_filename,
                "thumbnails": thumbnails,
                "message": "Thumbnails regenerated successfully",
            })
        except Exception as e:
            logger.error(f"Error regenerating thumbnails for file {file_pk}: {e}", exc_info=True)
            return Response(
                {"detail": "Failed to regenerate thumbnails."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        summary="Delete thumbnails",
        description="Delete all thumbnails for a file.",
        parameters=[
            OpenApiParameter(
                name='file_pk',
                description='File UUID',
                required=True,
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH
            ),
        ],
        responses={
            204: OpenApiResponse(description="Thumbnails deleted"),
            403: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT
        }
    )
    def delete(self, request, file_pk):
        """Delete all thumbnails for a file."""
        file_instance = self.get_file_instance(request, file_pk)
        
        if not file_instance:
            return Response(
                {"detail": "File not found or you don't have access."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check permissions (uploader or admin)
        is_uploader = file_instance.uploaded_by == request.user
        is_admin = request.user.is_staff or request.user.is_superuser
        if not (is_uploader or is_admin):
            return Response(
                {"detail": "You do not have permission to delete thumbnails for this file."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            TransformationService.delete_thumbnails(file_instance)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            logger.error(f"Error deleting thumbnails for file {file_pk}: {e}", exc_info=True)
            return Response(
                {"detail": "Failed to delete thumbnails."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )