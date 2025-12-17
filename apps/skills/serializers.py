"""
Serializers for the Skills app.

Provides serialization for:
- Skill: Skill/competency definitions
- ModuleSkill: Module-skill mappings
- LearnerSkillProgress: Learner progress on skills
- AssessmentSkillMapping: Assessment question to skill mappings
"""

from rest_framework import serializers

from .models import (
    AssessmentSkillMapping,
    LearnerSkillProgress,
    ModuleSkill,
    Skill,
)


# --- Skill Serializers ---


class SkillListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for skill listings."""
    category_display = serializers.CharField(
        source='get_category_display', read_only=True
    )
    children_count = serializers.SerializerMethodField()
    parent_name = serializers.CharField(
        source='parent.name', read_only=True, allow_null=True
    )

    class Meta:
        model = Skill
        fields = (
            "id",
            "name",
            "slug",
            "category",
            "category_display",
            "is_active",
            "parent",
            "parent_name",
            "children_count",
            "created_at",
        )
        read_only_fields = ("id", "slug", "children_count", "created_at")

    def get_children_count(self, obj):
        return obj.children.filter(is_active=True).count()


class SkillDetailSerializer(serializers.ModelSerializer):
    """Full serializer for skill details."""
    category_display = serializers.CharField(
        source='get_category_display', read_only=True
    )
    parent_name = serializers.CharField(
        source='parent.name', read_only=True, allow_null=True
    )
    children = serializers.SerializerMethodField()
    ancestors = serializers.SerializerMethodField()
    module_count = serializers.SerializerMethodField()
    learner_count = serializers.SerializerMethodField()

    class Meta:
        model = Skill
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "category",
            "category_display",
            "parent",
            "parent_name",
            "is_active",
            "external_id",
            "tags",
            "children",
            "ancestors",
            "module_count",
            "learner_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "slug",
            "children",
            "ancestors",
            "module_count",
            "learner_count",
            "created_at",
            "updated_at",
        )

    def get_children(self, obj):
        children = obj.children.filter(is_active=True)[:10]  # Limit for performance
        return SkillListSerializer(children, many=True).data

    def get_ancestors(self, obj):
        ancestors = obj.get_ancestors()
        return [{'id': str(a.id), 'name': a.name, 'slug': a.slug} for a in ancestors]

    def get_module_count(self, obj):
        return obj.module_mappings.count()

    def get_learner_count(self, obj):
        return obj.learner_progress.filter(proficiency_score__gt=0).count()


class SkillCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating and updating skills."""

    class Meta:
        model = Skill
        fields = (
            "name",
            "description",
            "category",
            "parent",
            "is_active",
            "external_id",
            "tags",
        )

    def validate_parent(self, value):
        """Ensure parent is from the same tenant."""
        if value:
            request = self.context.get('request')
            if request and hasattr(request, 'tenant'):
                if value.tenant_id != request.tenant.id:
                    raise serializers.ValidationError(
                        "Parent skill must belong to the same tenant."
                    )
        return value

    def validate(self, attrs):
        """Validate skill data."""
        # Prevent circular parent relationship on update
        if self.instance and attrs.get('parent'):
            parent = attrs['parent']
            # Check if the new parent is a descendant of this skill
            descendants = self.instance.get_all_children()
            if parent.id in [d.id for d in descendants]:
                raise serializers.ValidationError({
                    "parent": "Cannot set a descendant skill as parent (circular reference)."
                })
        return attrs

    def create(self, validated_data):
        request = self.context.get('request')
        if request and hasattr(request, 'tenant'):
            validated_data['tenant'] = request.tenant
        return super().create(validated_data)


# --- ModuleSkill Serializers ---


class ModuleSkillSerializer(serializers.ModelSerializer):
    """Serializer for module-skill mappings."""
    skill_name = serializers.CharField(source='skill.name', read_only=True)
    skill_slug = serializers.CharField(source='skill.slug', read_only=True)
    skill_category = serializers.CharField(source='skill.category', read_only=True)
    module_title = serializers.CharField(source='module.title', read_only=True)
    contribution_level_display = serializers.CharField(
        source='get_contribution_level_display', read_only=True
    )

    class Meta:
        model = ModuleSkill
        fields = (
            "id",
            "module",
            "module_title",
            "skill",
            "skill_name",
            "skill_slug",
            "skill_category",
            "contribution_level",
            "contribution_level_display",
            "proficiency_gained",
            "is_primary",
            "order",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "skill_name",
            "skill_slug",
            "skill_category",
            "module_title",
            "contribution_level_display",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        """Validate module-skill mapping."""
        module = attrs.get('module') or (self.instance.module if self.instance else None)
        skill = attrs.get('skill') or (self.instance.skill if self.instance else None)
        
        if module and skill:
            # Ensure skill belongs to the same tenant as the course
            if skill.tenant_id != module.course.tenant_id:
                raise serializers.ValidationError({
                    "skill": "Skill must belong to the same tenant as the module's course."
                })
        
        return attrs


class ModuleSkillBulkCreateSerializer(serializers.Serializer):
    """Serializer for bulk creating module-skill mappings."""
    skill_ids = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="List of skill IDs to add to the module"
    )
    contribution_level = serializers.ChoiceField(
        choices=ModuleSkill.ContributionLevel.choices,
        default=ModuleSkill.ContributionLevel.DEVELOPS
    )
    proficiency_gained = serializers.IntegerField(
        default=10, min_value=1, max_value=100
    )

    def validate_skill_ids(self, value):
        """Validate that all skill IDs exist and belong to the correct tenant."""
        request = self.context.get('request')
        if request and hasattr(request, 'tenant'):
            existing_skills = Skill.objects.filter(
                id__in=value,
                tenant=request.tenant,
                is_active=True
            ).values_list('id', flat=True)
            
            missing = set(str(v) for v in value) - set(str(e) for e in existing_skills)
            if missing:
                raise serializers.ValidationError(
                    f"Skills not found or inactive: {', '.join(missing)}"
                )
        return value


# --- LearnerSkillProgress Serializers ---


class LearnerSkillProgressSerializer(serializers.ModelSerializer):
    """Serializer for learner skill progress."""
    skill_name = serializers.CharField(source='skill.name', read_only=True)
    skill_slug = serializers.CharField(source='skill.slug', read_only=True)
    skill_category = serializers.CharField(source='skill.category', read_only=True)
    proficiency_level_display = serializers.CharField(
        source='get_proficiency_level_display', read_only=True
    )
    progress_trend = serializers.SerializerMethodField()
    user_email = serializers.CharField(source='user.email', read_only=True)

    class Meta:
        model = LearnerSkillProgress
        fields = (
            "id",
            "user",
            "user_email",
            "skill",
            "skill_name",
            "skill_slug",
            "skill_category",
            "proficiency_score",
            "proficiency_level",
            "proficiency_level_display",
            "progress_trend",
            "last_assessed_at",
            "last_practiced_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "user",
            "user_email",
            "skill_name",
            "skill_slug",
            "skill_category",
            "proficiency_level",
            "proficiency_level_display",
            "progress_trend",
            "created_at",
            "updated_at",
        )

    def get_progress_trend(self, obj):
        return obj.get_progress_trend(days=30)


class LearnerSkillProgressDetailSerializer(LearnerSkillProgressSerializer):
    """Extended serializer with full history for detailed views."""
    recent_history = serializers.SerializerMethodField()
    contributing_modules_count = serializers.SerializerMethodField()
    contributing_assessments_count = serializers.SerializerMethodField()

    class Meta(LearnerSkillProgressSerializer.Meta):
        fields = LearnerSkillProgressSerializer.Meta.fields + (
            "recent_history",
            "contributing_modules_count",
            "contributing_assessments_count",
        )

    def get_recent_history(self, obj):
        """Get last 10 history entries."""
        return obj.progress_history[-10:] if obj.progress_history else []

    def get_contributing_modules_count(self, obj):
        return len(obj.contributing_modules) if obj.contributing_modules else 0

    def get_contributing_assessments_count(self, obj):
        return len(obj.contributing_assessments) if obj.contributing_assessments else 0


class LearnerSkillSummarySerializer(serializers.Serializer):
    """Serializer for learner skill summary/dashboard."""
    total_skills = serializers.IntegerField()
    skills_in_progress = serializers.IntegerField()
    skills_mastered = serializers.IntegerField()
    average_proficiency = serializers.FloatField()
    strongest_category = serializers.CharField(allow_null=True)
    weakest_category = serializers.CharField(allow_null=True)
    recent_improvements = serializers.ListField()
    skills_by_category = serializers.DictField()


# --- AssessmentSkillMapping Serializers ---


class AssessmentSkillMappingSerializer(serializers.ModelSerializer):
    """Serializer for assessment-skill mappings."""
    skill_name = serializers.CharField(source='skill.name', read_only=True)
    skill_slug = serializers.CharField(source='skill.slug', read_only=True)
    question_text_preview = serializers.SerializerMethodField()
    assessment_title = serializers.CharField(
        source='question.assessment.title', read_only=True
    )
    proficiency_required_display = serializers.CharField(
        source='get_proficiency_required_display', read_only=True
    )
    proficiency_demonstrated_display = serializers.CharField(
        source='get_proficiency_demonstrated_display', read_only=True
    )

    class Meta:
        model = AssessmentSkillMapping
        fields = (
            "id",
            "question",
            "question_text_preview",
            "assessment_title",
            "skill",
            "skill_name",
            "skill_slug",
            "weight",
            "proficiency_required",
            "proficiency_required_display",
            "proficiency_demonstrated",
            "proficiency_demonstrated_display",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "skill_name",
            "skill_slug",
            "question_text_preview",
            "assessment_title",
            "proficiency_required_display",
            "proficiency_demonstrated_display",
            "created_at",
            "updated_at",
        )

    def get_question_text_preview(self, obj):
        """Return truncated question text for preview."""
        text = obj.question.question_text
        if len(text) > 100:
            return text[:100] + "..."
        return text

    def validate(self, attrs):
        """Validate assessment-skill mapping."""
        question = attrs.get('question') or (
            self.instance.question if self.instance else None
        )
        skill = attrs.get('skill') or (
            self.instance.skill if self.instance else None
        )
        
        if question and skill:
            # Ensure skill belongs to the same tenant as the assessment's course
            if skill.tenant_id != question.assessment.course.tenant_id:
                raise serializers.ValidationError({
                    "skill": "Skill must belong to the same tenant as the assessment's course."
                })
        
        return attrs


class AssessmentSkillMappingBulkCreateSerializer(serializers.Serializer):
    """Serializer for bulk creating assessment-skill mappings."""
    mappings = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of {question_id, skill_id, weight?, proficiency_required?, proficiency_demonstrated?}"
    )

    def validate_mappings(self, value):
        """Validate all mappings in the list."""
        request = self.context.get('request')
        
        for idx, mapping in enumerate(value):
            if 'question_id' not in mapping:
                raise serializers.ValidationError(
                    f"Mapping {idx}: question_id is required"
                )
            if 'skill_id' not in mapping:
                raise serializers.ValidationError(
                    f"Mapping {idx}: skill_id is required"
                )
            
            weight = mapping.get('weight', 1)
            if not (1 <= weight <= 10):
                raise serializers.ValidationError(
                    f"Mapping {idx}: weight must be between 1 and 10"
                )
        
        return value
