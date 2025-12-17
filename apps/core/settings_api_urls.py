from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .viewsets import PlatformSettingsViewSet, LTIPlatformViewSet, SSOConfigurationViewSet

app_name = 'platform_settings_api'

# Router for ViewSets with standard CRUD operations
router = DefaultRouter()
router.register(r'lti-platforms', LTIPlatformViewSet, basename='lti-platform')
router.register(r'sso-configurations', SSOConfigurationViewSet, basename='sso-configuration')

urlpatterns = [
    # List all settings (GET) and update all (PATCH)
    path('', PlatformSettingsViewSet.as_view({'get': 'list', 'patch': 'partial_update'}), name='settings-list'),
    
    # General settings
    path('general/', PlatformSettingsViewSet.as_view({'get': 'general', 'patch': 'update_general'}), name='settings-general'),
    
    # Storage settings
    path('storage/', PlatformSettingsViewSet.as_view({'get': 'storage', 'patch': 'update_storage'}), name='settings-storage'),
    path('storage/test/', PlatformSettingsViewSet.as_view({'post': 'test_storage'}), name='settings-storage-test'),
    
    # Email settings
    path('email/', PlatformSettingsViewSet.as_view({'get': 'email', 'patch': 'update_email'}), name='settings-email'),
    path('email/test/', PlatformSettingsViewSet.as_view({'post': 'test_email'}), name='settings-email-test'),
    
    # LTI and SSO ViewSets (registered via router)
    path('', include(router.urls)),
]
