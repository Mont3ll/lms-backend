"""
URL configuration for lms_backend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from apps.core.views import AdminDashboardStatsView

urlpatterns = [
    path("admin/", admin.site.urls),
    # API V1 URLs
    path(
        "api/v1/",
        include(
            [
                path(
                    "auth/", include("apps.users.urls")
                ),  # Auth endpoints (login, refresh)
                path("core/", include("apps.core.urls")),
                path(
                    "users/", include("apps.users.api_urls")
                ),  # User/Group management endpoints
                path("courses/", include("apps.courses.urls")),
                path("assessments/", include("apps.assessments.urls")),
                path("files/", include("apps.files.urls")),
                path("learning-paths/", include("apps.learning_paths.urls")),
                path("enrollments/", include("apps.enrollments.urls")),
                path("ai/", include("apps.ai_engine.urls")),
                path("notifications/", include("apps.notifications.urls")),
                path("analytics/", include("apps.analytics.urls")),

                # Learner-specific endpoints
                path('learner/', include('apps.core.learner_api_urls')),

                # Instructor-specific endpoints
                path('instructor/', include([
                    path('', include('apps.core.instructor_api_urls')),
                    path('', include('apps.assessments.instructor_api_urls')),
                ])),

                # Dedicated Admin API section
                path('admin/', include([
                    # Include user management viewsets if they are admin-only from apps.users.api_urls
                    # path('users/', include('apps.users.admin_api_urls')), # If you split them
                    path('dashboard-stats/', AdminDashboardStatsView.as_view(), name='admin-dashboard-stats'),
                    # Include other admin-specific viewsets/views here
                    # e.g., from apps.core if they are admin specific and not in the general 'core/' namespace
                    path('tenants/', include('apps.core.admin_api_urls')), # Tenant management endpoints
                    path('analytics/', include('apps.analytics.admin_api_urls')), # Analytics admin endpoints
                ])),
            ]
        ),
    ),
    # API Schema Documentation (Swagger/Redoc)
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/schema/swagger-ui/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/schema/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
]

# Serve media files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(
        settings.STATIC_URL, document_root=settings.STATIC_ROOT
    )  # If not using whitenoise in dev

# Note: Whitenoise handles static files in production via settings.py configuration
