import logging
import uuid
from rest_framework import generics, permissions, status, parsers, viewsets # Added viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import File, Folder, Tenant # Import Tenant
from .serializers import FileSerializer, FolderSerializer, FileUploadSerializer
from .services import StorageService, FileUploadError
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
