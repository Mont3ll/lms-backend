import logging
import time

from django.core.cache import cache
from django.utils.deprecation import MiddlewareMixin
from django.utils.functional import SimpleLazyObject

from .services import TenantService  # Assuming TenantService exists

logger = logging.getLogger(__name__)


def get_tenant(request):
    """Lazy function to get tenant.
    
    Supports tenant resolution via:
    1. X-Tenant-Slug header (useful for testing and API clients)
    2. Hostname-based lookup (production default)
    """
    if not hasattr(request, "_cached_tenant"):
        # First, try X-Tenant-Slug header (useful for testing and API clients)
        tenant_slug = request.META.get("HTTP_X_TENANT_SLUG")
        if tenant_slug:
            from .models import Tenant
            try:
                request._cached_tenant = Tenant.objects.get(slug=tenant_slug, is_active=True)
            except Tenant.DoesNotExist:
                request._cached_tenant = None
        else:
            # Fall back to hostname-based lookup
            hostname = request.get_host().split(":")[0]
            request._cached_tenant = TenantService.get_tenant_by_hostname(hostname)
    return request._cached_tenant


class TenantMiddleware(MiddlewareMixin):
    """
    Identifies the tenant based on the request hostname and sets it
    lazily on the request object.
    """

    def process_request(self, request):
        request.tenant = SimpleLazyObject(lambda: get_tenant(request))
        # If using django-tenants, activation would happen here based on request.tenant
        # try:
        #    if request.tenant:
        #        connection.set_tenant(request.tenant)
        #    else:
        #        connection.set_schema_to_public() # Or handle public/no tenant case
        # except Exception as e:
        #     logger.error(f"Error setting tenant context: {e}")
        #     # Handle error appropriately, maybe return 404 or 500


class MetricsMiddleware(MiddlewareMixin):
    """
    Basic middleware to track request processing time.
    """

    def process_request(self, request):
        request.start_time = time.time()

    def process_response(self, request, response):
        if hasattr(request, "start_time"):
            duration = time.time() - request.start_time
            status_code = response.status_code
            method = request.method
            path = request.path_info

            # Log metrics (e.g., to console, Prometheus, Datadog)
            logger.info(
                f"Request Metrics: {method} {path} Status:{status_code} Duration:{duration:.4f}s"
            )
            # You could push metrics to a dedicated system here
        return response


# Django's CacheMiddleware can be configured in settings.py
