from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q
from django.shortcuts import get_object_or_404
from .models import Tenant, TenantDomain
from .serializers import (
    TenantSerializer,
    TenantCreateSerializer, 
    TenantUpdateSerializer,
    TenantDomainManagementSerializer
)
from apps.users.permissions import IsAdminOrTenantAdmin
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from rest_framework.pagination import PageNumberPagination


class TenantPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


@extend_schema(tags=['Admin - Tenants'])
class TenantViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing Tenants (Superuser only).
    Provides CRUD operations and additional actions for tenant management.
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    pagination_class = TenantPagination
    
    def get_serializer_class(self):
        if self.action == 'create':
            return TenantCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return TenantUpdateSerializer
        return TenantSerializer
    
    def get_queryset(self):
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return Tenant.objects.none()

        user = self.request.user

        if not user.is_authenticated:
            return Tenant.objects.none()

        # Superusers can access all tenants
        if user.is_superuser:
            queryset = Tenant.objects.all()
        else:
            # Return all tenants for non-superusers (adjust as needed)
            queryset = Tenant.objects.all()

        # Apply filters
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | 
                Q(slug__icontains=search) |
                Q(domains__domain__icontains=search)
            ).distinct()

        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')

        return queryset.order_by('name')
    
    @extend_schema(
        summary="Toggle tenant active status",
        request=None,
        responses={200: TenantSerializer}
    )
    @action(detail=True, methods=['post'], url_path='toggle-status')
    def toggle_status(self, request, pk=None):
        """Toggle the active status of a tenant."""
        tenant = self.get_object()
        tenant.is_active = not tenant.is_active
        tenant.save(update_fields=['is_active'])
        
        serializer = self.get_serializer(tenant)
        return Response(serializer.data)
    
    @extend_schema(
        summary="Manage tenant domains",
        request=TenantDomainManagementSerializer,
        responses={200: {'message': 'string', 'domains_added': 'int', 'domains_removed': 'int'}}
    )
    @action(detail=True, methods=['post'], url_path='manage-domains')
    def manage_domains(self, request, pk=None):
        """Add or remove domains for a tenant."""
        tenant = self.get_object()
        serializer = TenantDomainManagementSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
        domains = serializer.validated_data['domains']
        action_type = serializer.validated_data['action']
        
        domains_added = 0
        domains_removed = 0
        
        if action_type == 'add':
            for domain in domains:
                # Check if domain already exists for any tenant
                if TenantDomain.objects.filter(domain=domain).exists():
                    continue  # Skip existing domains
                    
                TenantDomain.objects.create(
                    tenant=tenant,
                    domain=domain,
                    is_primary=not tenant.domains.exists()  # First domain is primary
                )
                domains_added += 1
                
        elif action_type == 'remove':
            domains_removed = TenantDomain.objects.filter(
                tenant=tenant,
                domain__in=domains
            ).delete()[0]
            
        return Response({
            'message': f'Successfully {action_type}ed domains',
            'domains_added': domains_added,
            'domains_removed': domains_removed
        })
    
    @extend_schema(
        summary="List tenant statistics",
        responses={200: {
            'total_users': 'int',
            'total_courses': 'int', 
            'total_enrollments': 'int',
            'active_users_30d': 'int'
        }}
    )
    @action(detail=True, methods=['get'], url_path='stats')
    def stats(self, request, pk=None):
        """Get statistics for a specific tenant."""
        tenant = self.get_object()
        
        # Import here to avoid circular imports
        from apps.users.models import User
        from apps.courses.models import Course
        from apps.enrollments.models import Enrollment
        from django.utils import timezone
        from datetime import timedelta
        
        thirty_days_ago = timezone.now() - timedelta(days=30)
        
        stats = {
            'total_users': User.objects.filter(tenant=tenant).count(),
            'total_courses': Course.objects.filter(tenant=tenant).count(),
            'total_enrollments': Enrollment.objects.filter(course__tenant=tenant).count(),
            'active_users_30d': User.objects.filter(
                tenant=tenant,
                last_login__gte=thirty_days_ago
            ).count()
        }
        
        return Response(stats)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            "results": serializer.data,
            "count": queryset.count(),
            "next": None,
            "previous": None
        })