from django.contrib import admin

from .models import (
    Tenant,
    TenantDomain,
    LTIPlatform,
    LTIDeployment,
    LTIResourceLink,
    SSOConfiguration,
)


class TenantDomainInline(admin.TabularInline):
    model = TenantDomain
    extra = 1


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "domain_list", "created_at")
    search_fields = ("name", "slug", "domains__domain")
    list_filter = ("is_active",)
    prepopulated_fields = {"slug": ("name",)}
    inlines = [TenantDomainInline]

    def domain_list(self, obj):
        return ", ".join([d.domain for d in obj.domains.all()])

    domain_list.short_description = "Domains"


@admin.register(TenantDomain)
class TenantDomainAdmin(admin.ModelAdmin):
    list_display = ("domain", "tenant", "is_primary", "created_at")
    list_filter = ("is_primary", "tenant")
    search_fields = ("domain", "tenant__name")
    list_select_related = ("tenant",)  # Optimize query


# --- LTI Admin ---


class LTIDeploymentInline(admin.TabularInline):
    model = LTIDeployment
    extra = 0
    readonly_fields = ("created_at",)


class LTIResourceLinkInline(admin.TabularInline):
    model = LTIResourceLink
    extra = 0
    readonly_fields = ("created_at", "lti_context_id", "lti_context_title")
    autocomplete_fields = ("course",)


@admin.register(LTIPlatform)
class LTIPlatformAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "issuer", "client_id", "is_active", "created_at")
    list_filter = ("is_active", "tenant")
    search_fields = ("name", "issuer", "client_id", "tenant__name")
    list_select_related = ("tenant",)
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = [LTIDeploymentInline, LTIResourceLinkInline]
    fieldsets = (
        (None, {
            "fields": ("id", "tenant", "name", "is_active"),
        }),
        ("Platform Configuration", {
            "fields": ("issuer", "client_id", "deployment_id"),
        }),
        ("Platform Endpoints", {
            "fields": ("auth_login_url", "auth_token_url", "keyset_url"),
        }),
        ("Tool Keys", {
            "fields": ("tool_private_key", "tool_public_key"),
            "classes": ("collapse",),
            "description": "RSA keys for signing/verifying LTI messages. Keep private key secure.",
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )


@admin.register(LTIDeployment)
class LTIDeploymentAdmin(admin.ModelAdmin):
    list_display = ("deployment_id", "platform", "is_active", "created_at")
    list_filter = ("is_active", "platform__tenant")
    search_fields = ("deployment_id", "platform__name", "platform__tenant__name")
    list_select_related = ("platform", "platform__tenant")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(LTIResourceLink)
class LTIResourceLinkAdmin(admin.ModelAdmin):
    list_display = ("resource_link_id", "platform", "lti_context_title", "course", "created_at")
    list_filter = ("platform__tenant", "platform")
    search_fields = (
        "resource_link_id",
        "lti_context_title",
        "lti_context_id",
        "platform__name",
        "course__title",
    )
    list_select_related = ("platform", "platform__tenant", "course")
    readonly_fields = ("id", "created_at", "updated_at")
    autocomplete_fields = ("course",)


# --- SSO Admin ---


@admin.register(SSOConfiguration)
class SSOConfigurationAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "provider_type", "is_active", "is_default", "created_at")
    list_filter = ("provider_type", "is_active", "is_default", "tenant")
    search_fields = ("name", "tenant__name", "idp_entity_id")
    list_select_related = ("tenant",)
    readonly_fields = ("id", "created_at", "updated_at")
    fieldsets = (
        (None, {
            "fields": ("id", "tenant", "name", "provider_type", "is_active", "is_default"),
        }),
        ("SAML Configuration", {
            "fields": (
                "idp_entity_id",
                "idp_sso_url",
                "idp_slo_url",
                "idp_x509_cert",
            ),
            "classes": ("collapse",),
            "description": "Configure these fields for SAML 2.0 identity providers.",
        }),
        ("OAuth/OIDC Configuration", {
            "fields": (
                "oauth_client_id",
                "oauth_client_secret",
                "oauth_authorization_url",
                "oauth_token_url",
                "oauth_userinfo_url",
                "oauth_scopes",
            ),
            "classes": ("collapse",),
            "description": "Configure these fields for OAuth 2.0 / OpenID Connect providers.",
        }),
        ("Attribute & Role Mapping", {
            "fields": ("attribute_mapping", "role_mapping"),
            "classes": ("collapse",),
            "description": "JSON mappings for user attributes and roles from the IdP.",
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )
