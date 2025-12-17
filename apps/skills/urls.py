"""
URL configuration for the Skills app.

Provides endpoints for:
- /skills/ - Skill CRUD operations
- /module-skills/ - Module-skill mappings
- /skill-progress/ - Learner skill progress tracking
- /assessment-skill-mappings/ - Assessment question to skill mappings
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .viewsets import (
    AssessmentSkillMappingViewSet,
    LearnerSkillProgressViewSet,
    ModuleSkillViewSet,
    SkillViewSet,
)

app_name = 'skills'

router = DefaultRouter()
router.register(r'skills', SkillViewSet, basename='skill')
router.register(r'module-skills', ModuleSkillViewSet, basename='module-skill')
router.register(r'skill-progress', LearnerSkillProgressViewSet, basename='skill-progress')
router.register(r'assessment-skill-mappings', AssessmentSkillMappingViewSet, basename='assessment-skill-mapping')

urlpatterns = [
    path('', include(router.urls)),
]

# URL Structure:
# 
# Skills:
# List/Create:              GET/POST    /api/v1/skills/skills/
# Retrieve/Update/Delete:   GET/PUT/DELETE /api/v1/skills/skills/{slug}/
# Get hierarchy:            GET         /api/v1/skills/skills/hierarchy/
# Get categories:           GET         /api/v1/skills/skills/categories/
# Get skill modules:        GET         /api/v1/skills/skills/{slug}/modules/
# Get progress stats:       GET         /api/v1/skills/skills/{slug}/progress-stats/
#
# Module-Skill Mappings:
# List/Create:              GET/POST    /api/v1/skills/module-skills/
# Retrieve/Update/Delete:   GET/PUT/DELETE /api/v1/skills/module-skills/{pk}/
# Bulk create:              POST        /api/v1/skills/module-skills/bulk-create/
#
# Learner Skill Progress:
# List:                     GET         /api/v1/skills/skill-progress/
# Retrieve:                 GET         /api/v1/skills/skill-progress/{pk}/
# My progress summary:      GET         /api/v1/skills/skill-progress/my-progress/
# Skill gaps:               GET         /api/v1/skills/skill-progress/skill-gaps/
#
# Assessment-Skill Mappings:
# List/Create:              GET/POST    /api/v1/skills/assessment-skill-mappings/
# Retrieve/Update/Delete:   GET/PUT/DELETE /api/v1/skills/assessment-skill-mappings/{pk}/
# Bulk create:              POST        /api/v1/skills/assessment-skill-mappings/bulk-create/
# Get coverage:             GET         /api/v1/skills/assessment-skill-mappings/coverage/?assessment_id=...
