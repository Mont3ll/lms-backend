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


class LTILineItem(TimestampedModel):
    """
    Represents an LTI AGS (Assignment and Grade Services) line item.
    Used for grade passback to LTI platforms.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    resource_link = models.ForeignKey(
        LTIResourceLink,
        on_delete=models.CASCADE,
        related_name="line_items",
        help_text="The resource link this line item belongs to",
    )
    # LTI line item identifier from the platform
    line_item_id = models.CharField(
        max_length=500,
        blank=True,
        help_text="Line item ID/URL from the LTI platform",
    )
    # Local reference to assessment (optional)
    assessment = models.ForeignKey(
        "assessments.Assessment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lti_line_items",
        help_text="Linked LMS assessment",
    )
    label = models.CharField(
        max_length=255,
        help_text="Display name for the line item",
    )
    score_maximum = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=100.00,
        help_text="Maximum score for this line item",
    )
    tag = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional tag for categorizing line items",
    )
    resource_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="Tool resource identifier",
    )
    # AGS endpoint URLs from the platform
    ags_endpoint = models.URLField(
        max_length=500,
        blank=True,
        help_text="AGS endpoint URL for this line item",
    )

    class Meta:
        verbose_name = _("LTI Line Item")
        verbose_name_plural = _("LTI Line Items")
        unique_together = [["resource_link", "line_item_id"]]

    def __str__(self):
        return f"{self.label} ({self.resource_link})"


class LTIGradeSubmission(TimestampedModel):
    """
    Tracks grade submissions to LTI platforms.
    Used for auditing and retry logic.
    """

    class SubmissionStatus(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        SUBMITTED = "SUBMITTED", _("Submitted")
        FAILED = "FAILED", _("Failed")
        RETRYING = "RETRYING", _("Retrying")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    line_item = models.ForeignKey(
        LTILineItem,
        on_delete=models.CASCADE,
        related_name="grade_submissions",
        help_text="The line item this grade belongs to",
    )
    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="lti_grade_submissions",
        help_text="The user this grade is for",
    )
    # LTI user identifier (sub claim)
    lti_user_id = models.CharField(
        max_length=255,
        help_text="LTI user identifier (sub claim from launch)",
    )
    score = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Score achieved",
    )
    score_maximum = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Maximum possible score",
    )
    comment = models.TextField(
        blank=True,
        help_text="Optional comment/feedback",
    )
    activity_progress = models.CharField(
        max_length=50,
        default="Completed",
        help_text="Activity progress (Initialized, Started, InProgress, Submitted, Completed)",
    )
    grading_progress = models.CharField(
        max_length=50,
        default="FullyGraded",
        help_text="Grading progress (FullyGraded, Pending, PendingManual, Failed, NotReady)",
    )
    # Submission tracking
    status = models.CharField(
        max_length=20,
        choices=SubmissionStatus.choices,
        default=SubmissionStatus.PENDING,
    )
    submitted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the grade was successfully submitted to the platform",
    )
    error_message = models.TextField(
        blank=True,
        help_text="Error message if submission failed",
    )
    retry_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of retry attempts",
    )

    class Meta:
        verbose_name = _("LTI Grade Submission")
        verbose_name_plural = _("LTI Grade Submissions")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Grade for {self.user} on {self.line_item.label}: {self.score}/{self.score_maximum}"


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


class PlatformSettings(TimestampedModel):
    """
    Singleton model for storing platform-wide settings.
    These settings can override environment variables when configured via admin UI.
    Only one instance should exist per tenant (or globally if no tenant).
    """

    class StorageBackend(models.TextChoices):
        LOCAL = "local", _("Local Filesystem")
        S3 = "s3", _("Amazon S3 / S3-Compatible")
        GCS = "gcs", _("Google Cloud Storage")
        AZURE = "azure", _("Azure Blob Storage")

    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.CASCADE,
        related_name="platform_settings",
        null=True,
        blank=True,
        help_text="Tenant these settings belong to. Null for global/default settings.",
    )

    # General Settings
    site_name = models.CharField(
        max_length=100,
        default="LMS Platform",
        help_text="The name of the platform displayed to users",
    )
    site_description = models.TextField(
        blank=True,
        max_length=500,
        help_text="A brief description of the platform",
    )
    default_language = models.CharField(
        max_length=10,
        default="en",
        help_text="Default language code (e.g., en, es, fr)",
    )
    timezone = models.CharField(
        max_length=50,
        default="UTC",
        help_text="Default timezone (e.g., UTC, America/New_York)",
    )
    support_email = models.EmailField(
        blank=True,
        help_text="Support contact email address",
    )
    terms_url = models.URLField(
        blank=True,
        help_text="URL to Terms of Service page",
    )
    privacy_url = models.URLField(
        blank=True,
        help_text="URL to Privacy Policy page",
    )
    logo_url = models.URLField(
        blank=True,
        help_text="URL to the platform logo image",
    )
    favicon_url = models.URLField(
        blank=True,
        help_text="URL to the platform favicon",
    )

    # Storage Settings
    storage_backend = models.CharField(
        max_length=20,
        choices=StorageBackend.choices,
        default=StorageBackend.LOCAL,
        help_text="File storage backend type",
    )
    # S3 / S3-compatible storage settings
    s3_bucket_name = models.CharField(max_length=255, blank=True)
    s3_region = models.CharField(max_length=50, blank=True, default="us-east-1")
    s3_access_key_id = models.CharField(max_length=255, blank=True)
    s3_secret_access_key = models.CharField(max_length=255, blank=True)
    s3_endpoint_url = models.URLField(blank=True, help_text="Custom endpoint for S3-compatible services")
    s3_custom_domain = models.CharField(max_length=255, blank=True, help_text="CDN or custom domain")
    # GCS settings
    gcs_bucket_name = models.CharField(max_length=255, blank=True)
    gcs_project_id = models.CharField(max_length=255, blank=True)
    # Azure settings
    azure_container_name = models.CharField(max_length=255, blank=True)
    azure_account_name = models.CharField(max_length=255, blank=True)
    azure_account_key = models.CharField(max_length=255, blank=True)
    # General file settings
    max_file_size_mb = models.PositiveIntegerField(
        default=50,
        help_text="Maximum file upload size in MB",
    )
    allowed_extensions = models.CharField(
        max_length=500,
        default="pdf,doc,docx,ppt,pptx,xls,xlsx,jpg,jpeg,png,gif,mp4,webm,mp3,zip",
        help_text="Comma-separated list of allowed file extensions",
    )

    # Email Settings
    smtp_host = models.CharField(max_length=255, blank=True)
    smtp_port = models.PositiveIntegerField(default=587)
    smtp_username = models.CharField(max_length=255, blank=True)
    smtp_password = models.CharField(max_length=255, blank=True)
    smtp_use_tls = models.BooleanField(default=True)
    smtp_use_ssl = models.BooleanField(default=False)
    default_from_email = models.EmailField(blank=True)
    default_from_name = models.CharField(max_length=255, blank=True)
    email_timeout = models.PositiveIntegerField(default=30, help_text="Email connection timeout in seconds")

    class Meta:
        verbose_name = _("Platform Settings")
        verbose_name_plural = _("Platform Settings")

    def __str__(self):
        if self.tenant:
            return f"Settings for {self.tenant.name}"
        return "Global Platform Settings"

    def save(self, *args, **kwargs):
        # Ensure only one settings instance per tenant (or one global)
        if not self.pk:
            existing = PlatformSettings.objects.filter(tenant=self.tenant).first()
            if existing:
                self.pk = existing.pk
                self.id = existing.id
        super().save(*args, **kwargs)

    @classmethod
    def get_settings(cls, tenant=None):
        """
        Get or create settings for the given tenant.
        Falls back to global settings if tenant-specific don't exist.
        """
        if tenant:
            settings, _ = cls.objects.get_or_create(tenant=tenant)
            return settings
        # Get or create global settings
        settings, _ = cls.objects.get_or_create(tenant__isnull=True)
        return settings
