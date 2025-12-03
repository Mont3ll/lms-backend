import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import TimestampedModel


class Tenant(TimestampedModel):
    """
    Represents a tenant (organization) in the multi-tenant system.
    Simplified model; consider django-tenants for full implementation.
    """

    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(
        max_length=255,
        unique=True,
        help_text="Unique identifier used in URLs/subdomains",
    )
    is_active = models.BooleanField(default=True)
    # Tenant-specific settings
    theme_config = models.JSONField(
        default=dict, blank=True, help_text="Tenant theme settings (colors, logo, etc.)"
    )
    feature_flags = models.JSONField(
        default=dict, blank=True, help_text="Features enabled for this tenant"
    )

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        from apps.common.utils import generate_unique_slug

        if not self.slug:
            self.slug = generate_unique_slug(self, source_field="name")
        super().save(*args, **kwargs)

    # Add methods to easily check feature flags, e.g.:
    # def has_feature(self, feature_name):
    #     return self.feature_flags.get(feature_name, False)


class TenantDomain(TimestampedModel):
    """
    Associates a domain name with a specific Tenant.
    Used by middleware to identify the tenant based on the request hostname.
    """

    tenant = models.ForeignKey(Tenant, related_name="domains", on_delete=models.CASCADE)
    domain = models.CharField(max_length=255, unique=True)
    is_primary = models.BooleanField(
        default=False, help_text="The main domain for this tenant"
    )

    def __str__(self):
        return f"{self.domain} ({self.tenant.name})"

    class Meta:
        verbose_name = "Tenant Domain"
        verbose_name_plural = "Tenant Domains"
        ordering = ["tenant__name", "-is_primary", "domain"]


class LTIPlatform(TimestampedModel):
    """
    Represents an LTI 1.3 Platform (Consumer) registration.
    Stores the platform configuration for LTI launches.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="lti_platforms",
        help_text="The tenant this LTI platform belongs to",
    )
    name = models.CharField(
        max_length=255, help_text="Human-readable name for this platform"
    )
    issuer = models.URLField(
        max_length=500, help_text="Platform issuer URL (iss claim in JWT)"
    )
    client_id = models.CharField(
        max_length=255, help_text="OAuth2 client ID assigned by the platform"
    )
    deployment_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="Deployment ID (optional, some platforms use multiple)",
    )

    # Platform endpoints
    auth_login_url = models.URLField(
        max_length=500, help_text="Platform's OIDC authorization endpoint"
    )
    auth_token_url = models.URLField(
        max_length=500, help_text="Platform's OAuth2 token endpoint"
    )
    keyset_url = models.URLField(
        max_length=500, help_text="Platform's public keyset (JWKS) URL"
    )

    # Tool (LMS) keys for this platform registration
    tool_private_key = models.TextField(
        help_text="PEM-encoded private key for signing messages to this platform"
    )
    tool_public_key = models.TextField(
        help_text="PEM-encoded public key for the platform to verify our signatures"
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("LTI Platform")
        verbose_name_plural = _("LTI Platforms")
        unique_together = [["tenant", "issuer", "client_id"]]
        ordering = ["tenant__name", "name"]

    def __str__(self):
        return f"{self.name} ({self.tenant.name})"


class LTIDeployment(TimestampedModel):
    """
    Represents an LTI 1.3 deployment within a platform.
    A platform can have multiple deployments.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    platform = models.ForeignKey(
        LTIPlatform, on_delete=models.CASCADE, related_name="deployments"
    )
    deployment_id = models.CharField(
        max_length=255, help_text="Deployment ID provided by the platform"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("LTI Deployment")
        verbose_name_plural = _("LTI Deployments")
        unique_together = [["platform", "deployment_id"]]

    def __str__(self):
        return f"{self.deployment_id} ({self.platform.name})"


class LTIResourceLink(TimestampedModel):
    """
    Represents an LTI resource link to a specific course/content item.
    Maps LTI context to LMS courses.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    platform = models.ForeignKey(
        LTIPlatform, on_delete=models.CASCADE, related_name="resource_links"
    )
    resource_link_id = models.CharField(
        max_length=255, help_text="Resource link ID from LTI launch"
    )
    lti_context_id = models.CharField(
        max_length=255, blank=True, help_text="LTI context ID (typically course ID)"
    )
    lti_context_title = models.CharField(
        max_length=500, blank=True, help_text="LTI context title"
    )
    # Link to LMS course (optional - for lazy linking)
    course = models.ForeignKey(
        "courses.Course",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lti_resource_links",
        help_text="Linked LMS course",
    )

    class Meta:
        verbose_name = _("LTI Resource Link")
        verbose_name_plural = _("LTI Resource Links")
        unique_together = [["platform", "resource_link_id"]]

    def __str__(self):
        return f"{self.lti_context_title or self.resource_link_id}"


class SSOConfiguration(TimestampedModel):
    """
    Stores SSO (SAML/OAuth) configuration per tenant.
    Supports multiple SSO providers per tenant.
    """

    class ProviderType(models.TextChoices):
        SAML = "SAML", _("SAML 2.0")
        OAUTH_GOOGLE = "OAUTH_GOOGLE", _("Google OAuth 2.0")
        OAUTH_MICROSOFT = "OAUTH_MICROSOFT", _("Microsoft OAuth 2.0")
        OAUTH_GENERIC = "OAUTH_GENERIC", _("Generic OAuth 2.0")
        OIDC = "OIDC", _("OpenID Connect")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="sso_configurations",
        help_text="The tenant this SSO configuration belongs to",
    )
    name = models.CharField(
        max_length=255, help_text="Human-readable name for this SSO provider"
    )
    provider_type = models.CharField(
        max_length=50,
        choices=ProviderType.choices,
        help_text="Type of SSO provider",
    )
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(
        default=False,
        help_text="If true, users will be redirected here by default for SSO login",
    )

    # SAML-specific fields
    idp_entity_id = models.CharField(
        max_length=500,
        blank=True,
        help_text="SAML Identity Provider Entity ID",
    )
    idp_sso_url = models.URLField(
        max_length=500,
        blank=True,
        help_text="SAML IdP Single Sign-On URL",
    )
    idp_slo_url = models.URLField(
        max_length=500,
        blank=True,
        help_text="SAML IdP Single Logout URL (optional)",
    )
    idp_x509_cert = models.TextField(
        blank=True,
        help_text="SAML IdP X.509 certificate (PEM format)",
    )

    # OAuth/OIDC-specific fields
    oauth_client_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="OAuth/OIDC Client ID",
    )
    oauth_client_secret = models.CharField(
        max_length=500,
        blank=True,
        help_text="OAuth/OIDC Client Secret (encrypted in production)",
    )
    oauth_authorization_url = models.URLField(
        max_length=500,
        blank=True,
        help_text="OAuth authorization endpoint URL",
    )
    oauth_token_url = models.URLField(
        max_length=500,
        blank=True,
        help_text="OAuth token endpoint URL",
    )
    oauth_userinfo_url = models.URLField(
        max_length=500,
        blank=True,
        help_text="OAuth/OIDC userinfo endpoint URL",
    )
    oauth_scopes = models.CharField(
        max_length=500,
        blank=True,
        default="openid email profile",
        help_text="Space-separated list of OAuth scopes",
    )

    # Attribute mapping (JSON) - maps IdP attributes to user fields
    attribute_mapping = models.JSONField(
        default=dict,
        blank=True,
        help_text="JSON mapping of IdP attributes to user fields (e.g., {'email': 'mail', 'first_name': 'givenName'})",
    )

    # Role mapping (JSON) - maps IdP groups/roles to LMS roles
    role_mapping = models.JSONField(
        default=dict,
        blank=True,
        help_text="JSON mapping of IdP groups to LMS roles (e.g., {'admins': 'ADMIN', 'teachers': 'INSTRUCTOR'})",
    )

    class Meta:
        verbose_name = _("SSO Configuration")
        verbose_name_plural = _("SSO Configurations")
        ordering = ["tenant__name", "name"]

    def __str__(self):
        return f"{self.name} ({self.get_provider_type_display()}) - {self.tenant.name}"

    def save(self, *args, **kwargs):
        # Ensure only one default SSO config per tenant
        if self.is_default:
            SSOConfiguration.objects.filter(tenant=self.tenant, is_default=True).exclude(
                pk=self.pk
            ).update(is_default=False)
        super().save(*args, **kwargs)
