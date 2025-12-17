"""
Skills models for tracking learner competencies and skill development.

This module provides models for:
- Skill: Defines skills/competencies that can be learned
- ModuleSkill: Links modules to skills they teach
- LearnerSkillProgress: Tracks individual learner progress on skills
- AssessmentSkillMapping: Links assessment questions to skills they evaluate
"""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import TimestampedModel


class Skill(TimestampedModel):
    """
    Represents a skill or competency that can be learned and measured.
    
    Skills can be organized hierarchically (parent-child relationships) and
    belong to categories for better organization.
    """

    class Category(models.TextChoices):
        TECHNICAL = "TECHNICAL", _("Technical")
        SOFT = "SOFT", _("Soft Skills")
        DOMAIN = "DOMAIN", _("Domain Knowledge")
        LANGUAGE = "LANGUAGE", _("Language")
        METHODOLOGY = "METHODOLOGY", _("Methodology")
        TOOL = "TOOL", _("Tool/Technology")
        OTHER = "OTHER", _("Other")

    class ProficiencyLevel(models.TextChoices):
        """Standard proficiency levels for skill assessment."""
        NOVICE = "NOVICE", _("Novice")
        BEGINNER = "BEGINNER", _("Beginner")
        INTERMEDIATE = "INTERMEDIATE", _("Intermediate")
        ADVANCED = "ADVANCED", _("Advanced")
        EXPERT = "EXPERT", _("Expert")

    tenant = models.ForeignKey(
        'core.Tenant',
        on_delete=models.CASCADE,
        related_name='skills',
        help_text="The tenant this skill belongs to"
    )
    name = models.CharField(
        max_length=100,
        help_text="Name of the skill"
    )
    slug = models.SlugField(
        max_length=100,
        db_index=True,
        help_text="URL-friendly identifier for the skill"
    )
    description = models.TextField(
        blank=True,
        help_text="Detailed description of the skill"
    )
    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.OTHER,
        db_index=True,
        help_text="Category this skill belongs to"
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
        help_text="Parent skill for hierarchical organization"
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Whether this skill is actively used"
    )
    # Optional metadata for skill taxonomy
    external_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="External identifier (e.g., for skill frameworks like SFIA, ESCO)"
    )
    tags = models.JSONField(
        default=list,
        blank=True,
        help_text="Tags for additional categorization"
    )

    def __str__(self):
        return f"{self.name} ({self.tenant.name})"

    def save(self, *args, **kwargs):
        from django.utils.text import slugify
        
        if not self.slug:
            base_slug = slugify(self.name)
            if not base_slug:
                import uuid
                base_slug = str(uuid.uuid4())[:8]
            
            slug = base_slug
            counter = 1
            # Ensure uniqueness within tenant
            while Skill.objects.filter(
                tenant=self.tenant, slug=slug
            ).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_all_children(self, include_inactive: bool = False) -> models.QuerySet:
        """
        Get all descendant skills recursively.
        
        Args:
            include_inactive: Whether to include inactive skills
            
        Returns:
            QuerySet of all descendant Skill objects
        """
        all_children_ids = set()
        to_process = list(self.children.values_list('id', flat=True))
        
        while to_process:
            child_id = to_process.pop(0)
            if child_id not in all_children_ids:
                all_children_ids.add(child_id)
                grandchildren = Skill.objects.filter(parent_id=child_id)
                if not include_inactive:
                    grandchildren = grandchildren.filter(is_active=True)
                to_process.extend(grandchildren.values_list('id', flat=True))
        
        qs = Skill.objects.filter(id__in=all_children_ids)
        if not include_inactive:
            qs = qs.filter(is_active=True)
        return qs

    def get_ancestors(self) -> list:
        """
        Get all ancestor skills from parent to root.
        
        Returns:
            List of Skill objects from immediate parent to root
        """
        ancestors = []
        current = self.parent
        while current:
            ancestors.append(current)
            current = current.parent
        return ancestors

    class Meta:
        ordering = ['category', 'name']
        unique_together = ('tenant', 'slug')
        verbose_name = "Skill"
        verbose_name_plural = "Skills"


class ModuleSkill(TimestampedModel):
    """
    Links a module to skills it teaches or develops.
    
    This mapping allows the system to:
    - Track which skills are covered in each module
    - Calculate skill coverage across courses
    - Recommend modules based on skill gaps
    """

    class ContributionLevel(models.TextChoices):
        """How much a module contributes to skill development."""
        INTRODUCES = "INTRODUCES", _("Introduces")  # First exposure
        DEVELOPS = "DEVELOPS", _("Develops")  # Building competency
        REINFORCES = "REINFORCES", _("Reinforces")  # Practice and strengthen
        MASTERS = "MASTERS", _("Masters")  # Achieves proficiency

    module = models.ForeignKey(
        'courses.Module',
        on_delete=models.CASCADE,
        related_name='skill_mappings',
        help_text="The module that teaches this skill"
    )
    skill = models.ForeignKey(
        Skill,
        on_delete=models.CASCADE,
        related_name='module_mappings',
        help_text="The skill being taught"
    )
    contribution_level = models.CharField(
        max_length=15,
        choices=ContributionLevel.choices,
        default=ContributionLevel.DEVELOPS,
        help_text="How this module contributes to skill development"
    )
    proficiency_gained = models.PositiveIntegerField(
        default=10,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text="Estimated proficiency points gained (1-100) upon module completion"
    )
    is_primary = models.BooleanField(
        default=False,
        help_text="Whether this is a primary skill for the module"
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Order of skill importance within the module"
    )

    def __str__(self):
        return f"{self.module.title} -> {self.skill.name} ({self.contribution_level})"

    class Meta:
        ordering = ['module', '-is_primary', 'order']
        unique_together = ('module', 'skill')
        verbose_name = "Module Skill Mapping"
        verbose_name_plural = "Module Skill Mappings"


class LearnerSkillProgress(TimestampedModel):
    """
    Tracks a learner's progress and proficiency in a specific skill.
    
    This model maintains:
    - Current proficiency level (0-100)
    - Historical progress data
    - Source of skill development (which modules/assessments contributed)
    """

    user = models.ForeignKey(
        'users.User',
        on_delete=models.CASCADE,
        related_name='skill_progress',
        help_text="The learner"
    )
    skill = models.ForeignKey(
        Skill,
        on_delete=models.CASCADE,
        related_name='learner_progress',
        help_text="The skill being tracked"
    )
    proficiency_score = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Current proficiency score (0-100)"
    )
    proficiency_level = models.CharField(
        max_length=15,
        choices=Skill.ProficiencyLevel.choices,
        default=Skill.ProficiencyLevel.NOVICE,
        help_text="Current proficiency level"
    )
    # Track progress history
    progress_history = models.JSONField(
        default=list,
        blank=True,
        help_text="History of proficiency changes: [{date, score, source, source_id}]"
    )
    # Track contributing sources
    contributing_modules = models.JSONField(
        default=list,
        blank=True,
        help_text="List of module IDs that contributed to this skill"
    )
    contributing_assessments = models.JSONField(
        default=list,
        blank=True,
        help_text="List of assessment IDs that contributed to this skill"
    )
    # Timestamps for specific events
    last_assessed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this skill was last formally assessed"
    )
    last_practiced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this skill was last practiced/used"
    )

    def __str__(self):
        return f"{self.user.email} - {self.skill.name}: {self.proficiency_score}%"

    def update_proficiency(
        self,
        score_change: int,
        source_type: str,
        source_id: str,
        max_score: int = 100
    ) -> None:
        """
        Update the proficiency score and record the change.
        
        Args:
            score_change: Points to add (can be negative for decay)
            source_type: 'module', 'assessment', 'manual', etc.
            source_id: ID of the source that caused the change
            max_score: Maximum allowed score (default 100)
        """
        from django.utils import timezone
        
        old_score = self.proficiency_score
        self.proficiency_score = min(max(0, self.proficiency_score + score_change), max_score)
        
        # Update proficiency level based on score
        self.proficiency_level = self._calculate_level(self.proficiency_score)
        
        # Record in history
        history_entry = {
            'date': timezone.now().isoformat(),
            'old_score': old_score,
            'new_score': self.proficiency_score,
            'change': score_change,
            'source_type': source_type,
            'source_id': str(source_id)
        }
        self.progress_history.append(history_entry)
        
        # Update contributing sources
        if source_type == 'module' and str(source_id) not in self.contributing_modules:
            self.contributing_modules.append(str(source_id))
        elif source_type == 'assessment' and str(source_id) not in self.contributing_assessments:
            self.contributing_assessments.append(str(source_id))
        
        # Update timestamps
        if source_type == 'assessment':
            self.last_assessed_at = timezone.now()
        self.last_practiced_at = timezone.now()
        
        self.save()

    def _calculate_level(self, score: int) -> str:
        """Calculate proficiency level from score."""
        if score >= 90:
            return Skill.ProficiencyLevel.EXPERT
        elif score >= 70:
            return Skill.ProficiencyLevel.ADVANCED
        elif score >= 50:
            return Skill.ProficiencyLevel.INTERMEDIATE
        elif score >= 25:
            return Skill.ProficiencyLevel.BEGINNER
        return Skill.ProficiencyLevel.NOVICE

    def get_progress_trend(self, days: int = 30) -> dict:
        """
        Analyze progress trend over specified days.
        
        Args:
            days: Number of days to analyze
            
        Returns:
            Dict with trend analysis (direction, average_change, etc.)
        """
        from django.utils import timezone
        from datetime import timedelta
        
        cutoff = timezone.now() - timedelta(days=days)
        cutoff_str = cutoff.isoformat()
        
        recent_history = [
            entry for entry in self.progress_history
            if entry.get('date', '') >= cutoff_str
        ]
        
        if not recent_history:
            return {
                'direction': 'stable',
                'total_change': 0,
                'average_change': 0,
                'num_activities': 0
            }
        
        total_change = sum(entry.get('change', 0) for entry in recent_history)
        avg_change = total_change / len(recent_history)
        
        if total_change > 5:
            direction = 'improving'
        elif total_change < -5:
            direction = 'declining'
        else:
            direction = 'stable'
        
        return {
            'direction': direction,
            'total_change': total_change,
            'average_change': round(avg_change, 2),
            'num_activities': len(recent_history)
        }

    class Meta:
        ordering = ['-proficiency_score', 'skill__name']
        unique_together = ('user', 'skill')
        verbose_name = "Learner Skill Progress"
        verbose_name_plural = "Learner Skill Progress"


class AssessmentSkillMapping(TimestampedModel):
    """
    Links assessment questions to skills they evaluate.
    
    This enables:
    - Skill-based assessment analysis
    - Identifying skill gaps from assessment performance
    - Adaptive testing based on skill proficiency
    """

    question = models.ForeignKey(
        'assessments.Question',
        on_delete=models.CASCADE,
        related_name='skill_mappings',
        help_text="The assessment question"
    )
    skill = models.ForeignKey(
        Skill,
        on_delete=models.CASCADE,
        related_name='assessment_mappings',
        help_text="The skill being evaluated"
    )
    weight = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="How heavily this question weighs for the skill (1-10)"
    )
    proficiency_required = models.CharField(
        max_length=15,
        choices=Skill.ProficiencyLevel.choices,
        default=Skill.ProficiencyLevel.BEGINNER,
        help_text="Minimum proficiency level required to answer correctly"
    )
    proficiency_demonstrated = models.CharField(
        max_length=15,
        choices=Skill.ProficiencyLevel.choices,
        default=Skill.ProficiencyLevel.BEGINNER,
        help_text="Proficiency level demonstrated by correctly answering"
    )

    def __str__(self):
        return f"Q{self.question.order} ({self.question.assessment.title}) -> {self.skill.name}"

    class Meta:
        ordering = ['question', 'skill']
        unique_together = ('question', 'skill')
        verbose_name = "Assessment Skill Mapping"
        verbose_name_plural = "Assessment Skill Mappings"
