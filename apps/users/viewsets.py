from rest_framework import viewsets, permissions, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from .models import LearnerGroup, GroupMembership, Tenant
from .serializers import UserSerializer, UserCreateSerializer, LearnerGroupSerializer, GroupMembershipSerializer
from .permissions import IsAdminOrTenantAdmin
from apps.common.permissions import IsOwnerOrAdmin # Or specific permission
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

User = get_user_model()

@extend_schema(tags=['Admin - Users']) # Add tags for better Swagger grouping
class UserViewSet(viewsets.ModelViewSet):
    """
    API endpoint for Admins (Superuser or Tenant Admin) to manage users.
    """
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAdminUser] # Base check: only Django Admin/Staff
    # Add object permissions later if needed for more granular control

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        return UserSerializer

    def get_queryset(self):
        # Handle schema generation request - return none() to avoid tenant error
        if getattr(self, 'swagger_fake_view', False):
            return User.objects.none()

        user = self.request.user
        # Check if user is authenticated and staff (IsAdminUser permission handles this partially)
        if not (user and user.is_authenticated and user.is_staff):
             return User.objects.none() # Should not be reached if permissions are correct

        if user.is_superuser:
            return User.objects.select_related('profile', 'tenant').all().order_by('email')
        elif hasattr(user, 'tenant') and user.tenant: # Tenant Admin
            return User.objects.select_related('profile', 'tenant').filter(tenant=user.tenant).order_by('email')

        return User.objects.none() # Default deny

    def perform_create(self, serializer):
        # Logic moved from previous example, slightly refactored
        tenant = None
        if self.request.user.is_superuser:
            tenant_id = serializer.validated_data.get('tenant').id # Get tenant instance from validated data
            if not tenant_id:
                 # Should be caught by serializer required=True
                 raise serializers.ValidationError({"tenant": "Tenant must be specified by superuser."})
            # Serializer already validated the tenant exists
            tenant = serializer.validated_data.get('tenant')
        elif self.request.user.is_staff and hasattr(self.request.user, 'tenant') and self.request.user.tenant: # Tenant Admin
             # Ensure tenant in data matches admin's tenant
             data_tenant = serializer.validated_data.get('tenant')
             if data_tenant != self.request.user.tenant:
                 raise serializers.ValidationError({"tenant": "Tenant Admins can only create users within their own tenant."})
             tenant = self.request.user.tenant
        else:
             # Should not happen due to permission checks
             from rest_framework.exceptions import PermissionDenied
             raise PermissionDenied("You do not have permission to create users in this context.")

        # Save with the validated/determined tenant. Serializer handles creation.
        # Status defaults to model default ('INVITED' likely) unless specified in request data
        serializer.save(tenant=tenant)

@extend_schema(tags=['Groups'])
class LearnerGroupViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing Learner Groups within a tenant.
    Requires Tenant Admin or Instructor permissions (adjust as needed).
    """
    serializer_class = LearnerGroupSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrTenantAdmin] # Adjust permission as needed

    def get_queryset(self):
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return LearnerGroup.objects.none()

        tenant = self.request.tenant
        user = self.request.user # For potential role-based filtering later

        if not tenant and not user.is_superuser: # Must have tenant context or be superuser
             return LearnerGroup.objects.none()

        if user.is_superuser:
            # Superuser sees all groups? Or should filter by a tenant query param? Filter for now.
            tenant_filter_id = self.request.query_params.get('tenant_id')
            if tenant_filter_id:
                 return LearnerGroup.objects.filter(tenant_id=tenant_filter_id).select_related('tenant').prefetch_related('memberships__user')
            else:
                 return LearnerGroup.objects.all().select_related('tenant').prefetch_related('memberships__user') # Show all if no filter
        elif tenant:
            # Tenant users (Admins/Instructors) see groups in their tenant
            return LearnerGroup.objects.filter(tenant=tenant).select_related('tenant').prefetch_related('memberships__user')

        return LearnerGroup.objects.none()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    # --- Member Management Actions ---
    # These actions now handle adding/removing members via user IDs.

    @extend_schema(
        request={'application/json': {'example': {'user_ids': ['uuid1', 'uuid2']}}},
        responses={200: serializers.Serializer} # Simple success response
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdminOrTenantAdmin])
    def add_members(self, request, pk=None):
        group = self.get_object() # Fetches group based on pk, queryset filters apply tenant check
        user_ids = request.data.get('user_ids', [])

        if not user_ids or not isinstance(user_ids, list):
            return Response({"detail": "Provide a list of 'user_ids'."}, status=status.HTTP_400_BAD_REQUEST)

        added_count = 0
        errors = []
        # Ensure users exist and belong to the group's tenant
        users_to_add = User.objects.filter(id__in=user_ids, tenant=group.tenant)
        valid_user_ids = {str(u.id) for u in users_to_add} # Set of valid UUIDs as strings
        invalid_ids = [uid for uid in user_ids if str(uid) not in valid_user_ids]

        if invalid_ids:
            errors.append(f"Invalid or non-tenant user IDs: {', '.join(map(str, invalid_ids))}")

        memberships_to_create = []
        for user in users_to_add:
            # Check if membership already exists to avoid duplicate creation attempts if needed
            if not GroupMembership.objects.filter(group=group, user=user).exists():
                 memberships_to_create.append(GroupMembership(group=group, user=user))

        if memberships_to_create:
             try:
                 GroupMembership.objects.bulk_create(memberships_to_create)
                 added_count = len(memberships_to_create)
             except Exception as e:
                 errors.append(f"Error during bulk creation: {e}")

        if errors:
             return Response({"detail": f"Added {added_count} members.", "errors": errors}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"detail": f"Successfully added {added_count} members."}, status=status.HTTP_200_OK)

    @extend_schema(
        request={'application/json': {'example': {'user_ids': ['uuid1', 'uuid2']}}},
        responses={200: serializers.Serializer}
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, IsAdminOrTenantAdmin])
    def remove_members(self, request, pk=None):
        group = self.get_object()
        user_ids = request.data.get('user_ids', [])
        if not user_ids or not isinstance(user_ids, list):
            return Response({"detail": "Provide a list of 'user_ids'."}, status=status.HTTP_400_BAD_REQUEST)

        # Perform deletion
        deleted_count, _ = GroupMembership.objects.filter(group=group, user_id__in=user_ids).delete()

        return Response({"detail": f"Successfully removed {deleted_count} members."}, status=status.HTTP_200_OK)
