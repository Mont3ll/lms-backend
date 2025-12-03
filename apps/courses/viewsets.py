from rest_framework import viewsets, permissions, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.db.models import Prefetch, Max
from django.db import models
import uuid  # Add uuid import for instructor filtering
from .models import Course, Module, ContentItem, ContentVersion
from .serializers import CourseSerializer, ModuleSerializer, ContentItemSerializer, ContentVersionSerializer
from apps.users.models import User # Import User for role check
from apps.users.permissions import IsAdminOrTenantAdmin, IsInstructorOrAdmin
from .permissions import IsCourseInstructorOrAdmin, IsEnrolledOrInstructorOrAdmin
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

@extend_schema(tags=['Courses'])
class CourseViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing Courses. Instructors/Admins can create/edit.
    Learners can list/retrieve published courses they are enrolled in (logic might vary).
    """
    serializer_class = CourseSerializer
    lookup_field = 'slug'
    permission_classes = [permissions.IsAuthenticated] # Base permission, refined in methods

    def get_queryset(self):
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return Course.objects.none()

        tenant = self.request.tenant
        user = self.request.user

        if not user.is_authenticated: return Course.objects.none()

        # Base queryset filtered by tenant (or all for superuser)
        if user.is_superuser:
            queryset = Course.objects.all()
        elif tenant:
            queryset = Course.objects.filter(tenant=tenant)
        else:
            queryset = Course.objects.none() # Should not happen if tenant middleware works

        # Handle instructor filter parameter
        instructor_filter = self.request.query_params.get('instructor')
        if instructor_filter == 'me':
            # Filter to only courses taught by the current user
            queryset = queryset.filter(instructor=user)
        elif instructor_filter and instructor_filter != 'me':
            # Filter by specific instructor ID (for admin users)
            try:
                instructor_uuid = uuid.UUID(instructor_filter)
                queryset = queryset.filter(instructor_id=instructor_uuid)
            except ValueError:
                # Invalid UUID, return empty queryset
                return Course.objects.none()

        # Get enrolled filter from query params
        enrolled_filter = self.request.query_params.get('enrolled')

        # Filter based on user role and action
        if self.action == 'list':
            # Learners see published courses they are enrolled in? Or all published in tenant?
            # Instructors/Admins see all (draft, published, archived) within tenant?
            if not (user.is_staff or user.role == User.Role.INSTRUCTOR):
                # Filter for learners - show PUBLISHED only. Further filter by enrollment?
                queryset = queryset.filter(status=Course.Status.PUBLISHED)
                
                # Optional: Filter by user's enrollments if enrolled=true parameter is provided
                if enrolled_filter and enrolled_filter.lower() == 'true':
                    from apps.enrollments.models import Enrollment
                    enrolled_course_ids = Enrollment.objects.filter(
                        user=user, 
                        status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED]
                    ).values_list('course_id', flat=True)
                    queryset = queryset.filter(id__in=enrolled_course_ids)
            # Admins/Instructors see all statuses by default via base queryset
            elif enrolled_filter and enrolled_filter.lower() == 'true':
                # For instructors/admins, if enrolled=true, filter by courses where this user has active enrollments
                from apps.enrollments.models import Enrollment
                enrolled_course_ids = Enrollment.objects.filter(
                    user=user, 
                    status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED]
                ).values_list('course_id', flat=True)
                queryset = queryset.filter(id__in=enrolled_course_ids)

        # Prefetch related data for efficiency
        return queryset.select_related('tenant', 'instructor').prefetch_related(
             Prefetch('modules', queryset=Module.objects.order_by('order')),
             Prefetch('modules__content_items', queryset=ContentItem.objects.select_related('file').order_by('order'))
        ).order_by('title')


    def get_permissions(self):
        """ Assign permissions based on action. """
        if self.action in ['list', 'retrieve']:
            # Let get_queryset handle filtering visibility based on role/status/enrollment
            return [permissions.IsAuthenticated()]
        elif self.action in ['create']:
            # Check if user has role INSTRUCTOR or ADMIN/STAFF
            return [permissions.IsAuthenticated(), IsInstructorOrAdmin()]
        elif self.action in ['update', 'partial_update', 'destroy', 'publish', 'archive']:
            # Check if user is instructor of *this specific course* or admin
            return [permissions.IsAuthenticated(), IsCourseInstructorOrAdmin()]
        # Default deny for other potential actions
        return [permissions.IsAdminUser()]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def perform_create(self, serializer):
        tenant = self.request.tenant
        if not tenant and not self.request.user.is_superuser: # Superuser might create for a tenant
             raise serializers.ValidationError("Tenant context required.")

        # If superuser, tenant must be provided in request data
        req_tenant = serializer.validated_data.get('tenant', tenant) # Prefer explicit tenant if provided
        if not req_tenant:
             raise serializers.ValidationError({"tenant": "Tenant must be specified."})

        # Assign instructor automatically if not provided and user is instructor
        instructor = serializer.validated_data.get('instructor')
        if not instructor and self.request.user.role == User.Role.INSTRUCTOR:
             instructor = self.request.user

        serializer.save(tenant=req_tenant, instructor=instructor)

    # --- Custom Actions ---
    @extend_schema(request=None, responses={200: CourseSerializer})
    @action(detail=True, methods=['post'], permission_classes=[IsCourseInstructorOrAdmin])
    def publish(self, request, slug=None):
        course = self.get_object() # Permission check done by get_permissions
        if course.status == Course.Status.PUBLISHED:
             return Response({'detail': 'Course is already published.'}, status=status.HTTP_400_BAD_REQUEST)
        course.status = Course.Status.PUBLISHED
        course.save(update_fields=['status', 'updated_at'])
        serializer = self.get_serializer(course)
        return Response(serializer.data)

    @extend_schema(request=None, responses={200: CourseSerializer})
    @action(detail=True, methods=['post'], permission_classes=[IsCourseInstructorOrAdmin])
    def archive(self, request, slug=None):
        course = self.get_object()
        if course.status == Course.Status.ARCHIVED:
             return Response({'detail': 'Course is already archived.'}, status=status.HTTP_400_BAD_REQUEST)
        course.status = Course.Status.ARCHIVED
        course.save(update_fields=['status', 'updated_at'])
        serializer = self.get_serializer(course)
        return Response(serializer.data)


@extend_schema(tags=['Courses']) # Add to Courses tag group
class ModuleViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing Modules within a specific Course.
    Accessed via nested routes like /api/v1/courses/{course_slug}/modules/
    Requires Instructor/Admin permissions for the parent course.
    """
    serializer_class = ModuleSerializer
    permission_classes = [permissions.IsAuthenticated, IsCourseInstructorOrAdmin] # Check permission on parent course

    def get_queryset(self):
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return Module.objects.none()

        # Get course slug from URL kwargs provided by nested router
        course_slug = self.kwargs.get('nested_1_slug')  # Updated to use the correct parameter name
        if not course_slug: return Module.objects.none() # Should not happen with nested router

        # Filter modules by course slug. Tenant check happens implicitly via parent permission.
        # Prefetch content items for nested serialization
        return Module.objects.filter(course__slug=course_slug).prefetch_related(
            Prefetch('content_items', queryset=ContentItem.objects.select_related('file').order_by('order'))
        ).order_by('order')

    def perform_create(self, serializer):
        course_slug = self.kwargs.get('nested_1_slug')  # Updated to use the correct parameter name
        
        # Get tenant context from request
        tenant = self.request.tenant
        user = self.request.user
        
        # Build the course lookup query with proper tenant filtering
        course_query = {'slug': course_slug}
        
        # Apply tenant filtering unless user is superuser
        if not user.is_superuser and tenant:
            course_query['tenant'] = tenant
        
        # Permission already checked, fetch course safely with tenant context
        course = get_object_or_404(Course, **course_query)
        
        # Assign order automatically (last + 1)
        last_order = Module.objects.filter(course=course).aggregate(Max('order'))['order__max'] or 0
        serializer.save(course=course, order=last_order + 1)

    @extend_schema(
        request={
            'type': 'object',
            'properties': {
                'modules': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'id': {'type': 'string'},
                            'order': {'type': 'integer'},
                            'content_items': {
                                'type': 'array',
                                'items': {
                                    'type': 'object',
                                    'properties': {
                                        'id': {'type': 'string'},
                                        'order': {'type': 'integer'}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        responses={200: ModuleSerializer(many=True)},
        summary="Bulk update module and content item ordering"
    )
    @action(detail=False, methods=['put'], url_path='bulk-update')
    def bulk_update(self, request, **kwargs):
        """
        Bulk update module and content item ordering for drag-and-drop functionality.
        Expects a list of modules with their new order and optionally their content items with new orders.
        """
        course_slug = self.kwargs.get('nested_1_slug')
        if not course_slug:
            return Response(
                {'error': 'Course slug not found'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get tenant context from request
        tenant = self.request.tenant
        user = self.request.user
        
        # Build the course lookup query with proper tenant filtering
        course_query = {'slug': course_slug}
        
        # Apply tenant filtering unless user is superuser
        if not user.is_superuser and tenant:
            course_query['tenant'] = tenant
        
        # Get the course with permission check
        course = get_object_or_404(Course, **course_query)
        
        modules_data = request.data.get('modules', [])
        if not modules_data:
            return Response(
                {'error': 'No modules data provided'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Get IDs of modules that should exist after the update
            updated_module_ids = [module_data.get('id') for module_data in modules_data if module_data.get('id')]
            
            # Delete modules that are not in the updated list
            deleted_count = Module.objects.filter(
                course=course
            ).exclude(
                id__in=updated_module_ids
            ).count()
            
            if deleted_count > 0:
                Module.objects.filter(
                    course=course
                ).exclude(
                    id__in=updated_module_ids
                ).delete()

            # Update module orders and content items
            for module_data in modules_data:
                module_id = module_data.get('id')
                new_order = module_data.get('order')
                
                if module_id and new_order is not None:
                    # Update module order and title if provided
                    update_fields = {'order': new_order}
                    if 'title' in module_data:
                        update_fields['title'] = module_data['title']
                    
                    Module.objects.filter(
                        id=module_id, 
                        course=course
                    ).update(**update_fields)
                
                # Handle content items for this module
                content_items_data = module_data.get('content_items', [])
                
                # Get IDs of content items that should exist after the update
                updated_content_item_ids = [
                    item_data.get('id') for item_data in content_items_data 
                    if item_data.get('id')
                ]
                
                # Delete content items that are not in the updated list for this module
                if module_id:
                    ContentItem.objects.filter(
                        module_id=module_id
                    ).exclude(
                        id__in=updated_content_item_ids
                    ).delete()
                
                # Update content item orders
                for item_data in content_items_data:
                    item_id = item_data.get('id')
                    item_order = item_data.get('order')
                    
                    if item_id and item_order is not None:
                        ContentItem.objects.filter(
                            id=item_id,
                            module_id=module_id
                        ).update(order=item_order)

            # Return updated modules
            updated_modules = self.get_queryset()
            serializer = self.get_serializer(updated_modules, many=True)
            return Response(serializer.data)

        except Exception as e:
            return Response(
                {'error': f'Failed to update modules: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # Override perform_update/destroy if specific logic needed for modules


@extend_schema(tags=['Courses']) # Add to Courses tag group
class ContentItemViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing Content Items within a specific Module.
    Accessed via nested routes like /api/v1/courses/{course_slug}/modules/{module_pk}/items/
    Requires Instructor/Admin permissions for the parent course.
    """
    serializer_class = ContentItemSerializer
    permission_classes = [permissions.IsAuthenticated, IsCourseInstructorOrAdmin] # Check permission on parent course

    def get_queryset(self):
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return ContentItem.objects.none()

        module_pk = self.kwargs.get('nested_2_pk')  # Fixed parameter name for nested router
        if not module_pk: return ContentItem.objects.none()

        # Filter by module pk. Tenant/Course check happens implicitly via parent permission.
        return ContentItem.objects.filter(module_id=module_pk).select_related('module', 'file').order_by('order')

    def perform_create(self, serializer):
        module_pk = self.kwargs.get('nested_2_pk')  # Fixed parameter name for nested router
        # Permission checked, fetch module safely
        module_instance = get_object_or_404(Module, pk=module_pk)
        # TODO: Add logic here or in serializer to validate/link file_id/assessment_id based on content_type
        last_order = ContentItem.objects.filter(module=module_instance).aggregate(Max('order'))['order__max'] or 0
        serializer.save(module=module_instance, order=last_order + 1)

    # --- Versioning Actions ---
    # Note: Versioning logic moved here from views.py for better ViewSet cohesion

    @extend_schema(
        request=None, # Or define a simple comment field {'comment': 'string'}
        responses={201: ContentVersionSerializer},
        summary="Create Version Snapshot"
    )
    @action(detail=True, methods=['post'], url_path='create-version')
    def create_version(self, request, pk=None, **kwargs): # Get pk from URL
        """ Create a new version snapshot of this ContentItem """
        content_item = self.get_object() # Fetches ContentItem based on pk, checks permissions
        # Ensure user can edit this item (already covered by base permissions)

        last_version_num = content_item.versions.order_by('-version_number').first()
        new_version_num = (last_version_num.version_number + 1) if last_version_num else 1

        # Create snapshot data
        version_data = {
            "content_item": content_item, "user": request.user, "version_number": new_version_num,
            "comment": request.data.get('comment', ''), "content_type": content_item.content_type,
            "text_content": content_item.text_content, "external_url": content_item.external_url,
            "metadata": content_item.metadata,
            # TODO: Add file/assessment snapshot logic here if models are integrated
            # "file_version_id": content_item.file.current_version_id if content_item.file else None,
        }
        version = ContentVersion.objects.create(**version_data)
        serializer = ContentVersionSerializer(version)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: ContentVersionSerializer(many=True)}, summary="List Item Versions")
    @action(detail=True, methods=['get'], url_path='versions')
    def list_versions(self, request, pk=None, **kwargs): # Get pk from URL
        """ List historical versions for this ContentItem """
        content_item = self.get_object() # Fetches ContentItem based on pk, checks permissions
        versions = content_item.versions.select_related('user').order_by('-version_number')
        serializer = ContentVersionSerializer(versions, many=True)
        return Response(serializer.data)
