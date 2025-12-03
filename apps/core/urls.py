from django.urls import path
from .views import (
    health_check_view,
    AdminDashboardStatsView,
    # LTI views
    LTIOIDCLoginView,
    LTILaunchView,
    LTIJWKSView,
    # SSO views
    SSOLoginView,
    SAMLACSView,
    SAMLMetadataView,
    OAuthCallbackView,
    SSOProvidersView,
)

app_name = 'core'

urlpatterns = [
    # Health check
    path('health/', health_check_view, name='health_check'),

    # Admin Dashboard Stats
    path('admin/dashboard-stats/', AdminDashboardStatsView.as_view(), name='admin-dashboard-stats'),

    # LTI 1.3 endpoints
    path('lti/login/', LTIOIDCLoginView.as_view(), name='lti-oidc-login'),
    path('lti/launch/', LTILaunchView.as_view(), name='lti-launch'),
    path('lti/jwks/', LTIJWKSView.as_view(), name='lti-jwks'),
    path('lti/jwks/<uuid:platform_id>/', LTIJWKSView.as_view(), name='lti-jwks-platform'),

    # SSO endpoints
    path('sso/login/', SSOLoginView.as_view(), name='sso-login'),
    path('sso/saml/acs/', SAMLACSView.as_view(), name='saml-acs'),
    path('sso/saml/metadata/', SAMLMetadataView.as_view(), name='saml-metadata'),
    path('sso/saml/metadata/<uuid:config_id>/', SAMLMetadataView.as_view(), name='saml-metadata-config'),
    path('sso/oauth/callback/', OAuthCallbackView.as_view(), name='oauth-callback'),
    path('sso/providers/', SSOProvidersView.as_view(), name='sso-providers'),
]
