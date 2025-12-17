from django.urls import path
from .views import (
    health_check_view,
    AdminDashboardStatsView,
    # LTI views
    LTIOIDCLoginView,
    LTILaunchView,
    LTIJWKSView,
    # LTI AGS views
    LTIResourceLinkListView,
    LTIResourceLinkDetailView,
    LTILineItemListView,
    LTILineItemDetailView,
    LTIGradeSubmissionListView,
    LTIGradeSubmissionDetailView,
    LTISubmitGradeView,
    LTIRetryFailedSubmissionsView,
    # SSO views
    SSOLoginView,
    SAMLACSView,
    SAMLMetadataView,
    SAMLSLSView,
    SAMLLogoutView,
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

    # LTI AGS (Assignment and Grade Services) endpoints
    path('lti/resource-links/', LTIResourceLinkListView.as_view(), name='lti-resource-links'),
    path('lti/resource-links/<uuid:resource_link_id>/', LTIResourceLinkDetailView.as_view(), name='lti-resource-link-detail'),
    path('lti/resource-links/<uuid:resource_link_id>/line-items/', LTILineItemListView.as_view(), name='lti-line-items'),
    path('lti/line-items/<uuid:line_item_id>/', LTILineItemDetailView.as_view(), name='lti-line-item-detail'),
    path('lti/line-items/<uuid:line_item_id>/grades/', LTIGradeSubmissionListView.as_view(), name='lti-grade-submissions'),
    path('lti/grades/<uuid:submission_id>/', LTIGradeSubmissionDetailView.as_view(), name='lti-grade-submission-detail'),
    path('lti/line-items/<uuid:line_item_id>/submit-grade/', LTISubmitGradeView.as_view(), name='lti-submit-grade'),
    path('lti/grades/retry-failed/', LTIRetryFailedSubmissionsView.as_view(), name='lti-retry-failed-submissions'),

    # SSO endpoints
    path('sso/login/', SSOLoginView.as_view(), name='sso-login'),
    path('sso/saml/acs/', SAMLACSView.as_view(), name='saml-acs'),
    path('sso/saml/metadata/', SAMLMetadataView.as_view(), name='saml-metadata'),
    path('sso/saml/metadata/<uuid:config_id>/', SAMLMetadataView.as_view(), name='saml-metadata-config'),
    path('sso/saml/sls/', SAMLSLSView.as_view(), name='saml-sls'),
    path('sso/saml/sls/<uuid:config_id>/', SAMLSLSView.as_view(), name='saml-sls-config'),
    path('sso/saml/logout/', SAMLLogoutView.as_view(), name='saml-logout'),
    path('sso/oauth/callback/', OAuthCallbackView.as_view(), name='oauth-callback'),
    path('sso/providers/', SSOProvidersView.as_view(), name='sso-providers'),
]
