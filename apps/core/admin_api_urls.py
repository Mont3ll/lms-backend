from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .viewsets import TenantViewSet

app_name = 'core_admin_api' # Define an app_name for namespacing

router = DefaultRouter()
# Register TenantViewSet for managing Tenants
# Use empty string since 'tenants/' is already in the parent URL path
router.register(r'', TenantViewSet, basename='tenant-admin')

urlpatterns = [
    path('', include(router.urls)),
    # Add other admin-specific URL patterns from the 'core' app here if needed
]
