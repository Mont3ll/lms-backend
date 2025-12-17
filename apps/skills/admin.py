from django.contrib import admin

from .models import (
    AssessmentSkillMapping,
    LearnerSkillProgress,
    ModuleSkill,
    Skill,
)


class SkillChildrenInline(admin.TabularInline):
    """Inline for viewing child skills."""
    model = Skill
    fk_name = 'parent'
    extra = 0
    fields = ('name', 'category', 'is_active')
    readonly_fields = ('name', 'category', 'is_active')
    show_change_link = True
    verbose_name = "Child Skill"
    verbose_name_plural = "Child Skills"

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ModuleSkillInline(admin.TabularInline):
    """Inline for viewing modules that teach this skill."""
    model = ModuleSkill
    extra = 1
    autocomplete_fields = ['module']
    fields = ('module', 'contribution_level', 'proficiency_gained', 'is_primary', 'order')


class AssessmentSkillMappingInline(admin.TabularInline):
    """Inline for viewing assessment questions mapped to this skill."""
    model = AssessmentSkillMapping
    extra = 1
    autocomplete_fields = ['question']
    fields = ('question', 'weight', 'proficiency_required', 'proficiency_demonstrated')


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    """Admin configuration for Skills."""
    list_display = (
        'name',
        'tenant',
        'category',
        'parent',
        'is_active',
        'children_count',
        'modules_count',
        'created_at',
    )
    list_filter = ('category', 'is_active', 'tenant')
    search_fields = ('name', 'slug', 'description', 'tenant__name')
    prepopulated_fields = {'slug': ('name',)}
    list_select_related = ('tenant', 'parent')
    autocomplete_fields = ['parent', 'tenant']
    inlines = [SkillChildrenInline, ModuleSkillInline, AssessmentSkillMappingInline]
    ordering = ('tenant__name', 'category', 'name')
    
    fieldsets = (
        (None, {
            'fields': ('tenant', 'name', 'slug', 'category', 'parent')
        }),
        ('Details', {
            'fields': ('description', 'is_active', 'external_id', 'tags')
        }),
    )

    def children_count(self, obj):
        return obj.children.count()
    children_count.short_description = "Children"

    def modules_count(self, obj):
        return obj.module_mappings.count()
    modules_count.short_description = "Modules"


@admin.register(ModuleSkill)
class ModuleSkillAdmin(admin.ModelAdmin):
    """Admin configuration for Module-Skill mappings."""
    list_display = (
        'module',
        'skill',
        'contribution_level',
        'proficiency_gained',
        'is_primary',
        'order',
    )
    list_filter = (
        'contribution_level',
        'is_primary',
        'skill__tenant',
        'skill__category',
    )
    search_fields = (
        'module__title',
        'skill__name',
        'module__course__title',
    )
    list_select_related = ('module', 'skill', 'module__course', 'skill__tenant')
    autocomplete_fields = ['module', 'skill']
    ordering = ('module__course__title', 'module__order', '-is_primary', 'order')

    fieldsets = (
        (None, {
            'fields': ('module', 'skill')
        }),
        ('Configuration', {
            'fields': ('contribution_level', 'proficiency_gained', 'is_primary', 'order')
        }),
    )


@admin.register(LearnerSkillProgress)
class LearnerSkillProgressAdmin(admin.ModelAdmin):
    """Admin configuration for Learner Skill Progress tracking."""
    list_display = (
        'user',
        'skill',
        'proficiency_score',
        'proficiency_level',
        'last_assessed_at',
        'last_practiced_at',
        'updated_at',
    )
    list_filter = (
        'proficiency_level',
        'skill__tenant',
        'skill__category',
    )
    search_fields = (
        'user__email',
        'user__first_name',
        'user__last_name',
        'skill__name',
    )
    list_select_related = ('user', 'skill', 'skill__tenant')
    autocomplete_fields = ['user', 'skill']
    readonly_fields = (
        'progress_history',
        'contributing_modules',
        'contributing_assessments',
        'created_at',
        'updated_at',
    )
    ordering = ('-updated_at',)

    fieldsets = (
        (None, {
            'fields': ('user', 'skill')
        }),
        ('Proficiency', {
            'fields': ('proficiency_score', 'proficiency_level')
        }),
        ('Activity', {
            'fields': ('last_assessed_at', 'last_practiced_at')
        }),
        ('History (Read-only)', {
            'fields': ('progress_history', 'contributing_modules', 'contributing_assessments'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(AssessmentSkillMapping)
class AssessmentSkillMappingAdmin(admin.ModelAdmin):
    """Admin configuration for Assessment Question to Skill mappings."""
    list_display = (
        'question',
        'skill',
        'weight',
        'proficiency_required',
        'proficiency_demonstrated',
    )
    list_filter = (
        'proficiency_required',
        'proficiency_demonstrated',
        'skill__tenant',
        'skill__category',
    )
    search_fields = (
        'question__text',
        'skill__name',
        'question__assessment__title',
    )
    list_select_related = ('question', 'skill', 'question__assessment', 'skill__tenant')
    autocomplete_fields = ['question', 'skill']
    ordering = ('question__assessment__title', 'question__order', 'skill__name')

    fieldsets = (
        (None, {
            'fields': ('question', 'skill')
        }),
        ('Configuration', {
            'fields': ('weight', 'proficiency_required', 'proficiency_demonstrated')
        }),
    )
