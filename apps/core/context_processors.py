from .services import TenantService


def tenant_context(request):
    """
    Adds tenant information and basic settings to the template context.
    Mainly useful if rendering Django templates directly.
    """
    context = {"current_tenant": None, "tenant_settings": {}}
    # Accessing request.tenant triggers the lazy loader in middleware
    tenant = getattr(request, "tenant", None)
    if tenant:
        context["current_tenant"] = tenant
        # Fetch tenant specific settings (e.g., theme) if needed
        # Avoid doing heavy lookups here if possible; rely on cached/simple data
        context["tenant_settings"] = TenantService.get_tenant_settings(tenant)
    return context
