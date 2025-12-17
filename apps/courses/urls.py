from django.urls import path, include
from rest_framework_nested import routers # Use nested routers
from .viewsets import (
    CourseViewSet,
    ModuleViewSet,
    ContentItemViewSet,
    CoursePrerequisiteViewSet,
    ModulePrerequisiteViewSet,
)

app_name = 'courses'

# Base router for /courses/
router = routers.DefaultRouter()
router.register(r'courses', CourseViewSet, basename='course') # Uses 'slug' lookup

# Nested router for /courses/{course_slug}/modules/
# Don't specify lookup parameter to avoid double underscore issue
courses_router = routers.NestedDefaultRouter(router, r'courses')
courses_router.register(r'modules', ModuleViewSet, basename='course-module')
courses_router.register(r'prerequisites', CoursePrerequisiteViewSet, basename='course-prerequisite')

# Nested router for /courses/{course_slug}/modules/{module_pk}/items/
modules_router = routers.NestedDefaultRouter(courses_router, r'modules')
modules_router.register(r'items', ContentItemViewSet, basename='module-item')
modules_router.register(r'prerequisites', ModulePrerequisiteViewSet, basename='module-prerequisite')

urlpatterns = [
    path('', include(router.urls)),
    path('', include(courses_router.urls)),
    path('', include(modules_router.urls)),
    # Add bulk update endpoint for module reordering
    path('courses/<slug:course_slug>/modules/bulk-update/', 
         ModuleViewSet.as_view({'put': 'bulk_update'}), 
         name='course-modules-bulk-update'),
]

# Corrected URL Structure Examples:
# List/Create Courses:      /api/v1/courses/courses/
# Retrieve/Update Course:   /api/v1/courses/courses/{course_slug}/
# List/Create Modules:      /api/v1/courses/courses/{course_slug}/modules/
# Retrieve/Update Module:   /api/v1/courses/courses/{course_slug}/modules/{module_pk}/
# List/Create ContentItems: /api/v1/courses/courses/{course_slug}/modules/{module_pk}/items/
# Retrieve/Update Item:     /api/v1/courses/courses/{course_slug}/modules/{module_pk}/items/{item_pk}/
# 
# Course Prerequisites:
# List/Create:              /api/v1/courses/courses/{course_slug}/prerequisites/
# Retrieve/Update/Delete:   /api/v1/courses/courses/{course_slug}/prerequisites/{pk}/
# Get chain:                /api/v1/courses/courses/{course_slug}/prerequisites/chain/
# Check user met:           /api/v1/courses/courses/{course_slug}/prerequisites/check/
#
# Module Prerequisites:
# List/Create:              /api/v1/courses/courses/{course_slug}/modules/{module_pk}/prerequisites/
# Retrieve/Update/Delete:   /api/v1/courses/courses/{course_slug}/modules/{module_pk}/prerequisites/{pk}/
# Check user met:           /api/v1/courses/courses/{course_slug}/modules/{module_pk}/prerequisites/check/
