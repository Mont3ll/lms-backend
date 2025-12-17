import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import TimestampedModel
from apps.core.models import Tenant
from apps.users.models import User
from apps.files.models import File


class Course(TimestampedModel):
    """Represents a course in the LMS."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        PUBLISHED = "PUBLISHED", _("Published")
        ARCHIVED = "ARCHIVED", _("Archived")

    class DifficultyLevel(models.TextChoices):
        BEGINNER = "beginner", _("Beginner")
        INTERMEDIATE = "intermediate", _("Intermediate")
        ADVANCED = "advanced", _("Advanced")

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="courses")
    title = models.CharField(max_length=255)
    slug = models.SlugField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Unique identifier for the course URL",
    )
    description = models.TextField(blank=True)
    category = models.CharField(max_length=100, blank=True, help_text="Course category")
    difficulty_level = models.CharField(
        max_length=20, 
        choices=DifficultyLevel.choices, 
        default=DifficultyLevel.BEGINNER,
        help_text="Course difficulty level"
    )
    estimated_duration = models.PositiveIntegerField(
        default=1, 
        help_text="Estimated duration in hours"
    )
    price = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.00,
        help_text="Course price (0 for free courses)"
    )
    is_free = models.BooleanField(default=True, help_text="Whether the course is free")
    learning_objectives = models.JSONField(
        default=list, 
        blank=True, 
        help_text="List of learning objectives"
    )
    thumbnail = models.URLField(
        max_length=2048, 
        blank=True, 
        null=True, 
        help_text="Course thumbnail URL"
    )
    instructor = models.ForeignKey(
        User,
        related_name="courses_authored",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"role__in": [User.Role.INSTRUCTOR, User.Role.ADMIN]},
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    tags = models.JSONField(
        default=list, blank=True, help_text="List of tags for categorization"
    )
    # Add fields like category, estimated duration, prerequisites, thumbnail etc.
    # thumbnail = models.ForeignKey(File, on_delete=models.SET_NULL, null=True, blank=True, related_name='+') # Link to File model

    def __str__(self):
        return f"{self.title} ({self.tenant.name})"

    def save(self, *args, **kwargs):
        from apps.common.utils import generate_unique_slug

        if not self.slug:
            # Slug should be unique across all tenants if using subdomains/paths like /courses/my-slug/
            # If using tenant subdomains, slug only needs to be unique per tenant.
            # This implementation assumes globally unique slug. Adjust if needed.
            self.slug = generate_unique_slug(self, source_field="title")
        super().save(*args, **kwargs)

    class Meta:
        ordering = ["title"]
        # If slug is unique per tenant:
        # unique_together = ('tenant', 'slug')

    def get_all_prerequisites(self, prerequisite_type: str = None, include_indirect: bool = False) -> models.QuerySet:
        """
        Get all prerequisites for this course.
        
        Args:
            prerequisite_type: Filter by type (REQUIRED, RECOMMENDED, COREQUISITE)
            include_indirect: If True, recursively get prerequisites of prerequisites
            
        Returns:
            QuerySet of Course objects that are prerequisites
        """
        from apps.courses.models import CoursePrerequisite
        
        prereq_qs = CoursePrerequisite.objects.filter(course=self)
        if prerequisite_type:
            prereq_qs = prereq_qs.filter(prerequisite_type=prerequisite_type)
        
        direct_prereqs = prereq_qs.values_list('prerequisite_course_id', flat=True)
        
        if not include_indirect:
            return Course.objects.filter(id__in=direct_prereqs)
        
        # Recursively gather all prerequisites
        all_prereq_ids = set(direct_prereqs)
        to_process = list(direct_prereqs)
        
        while to_process:
            current_id = to_process.pop(0)
            indirect_prereqs = CoursePrerequisite.objects.filter(
                course_id=current_id
            )
            if prerequisite_type:
                indirect_prereqs = indirect_prereqs.filter(prerequisite_type=prerequisite_type)
            
            for prereq_id in indirect_prereqs.values_list('prerequisite_course_id', flat=True):
                if prereq_id not in all_prereq_ids:
                    all_prereq_ids.add(prereq_id)
                    to_process.append(prereq_id)
        
        return Course.objects.filter(id__in=all_prereq_ids)

    def are_prerequisites_met(self, user, check_type: str = 'REQUIRED') -> tuple[bool, list]:
        """
        Check if a user has met all prerequisites for this course.
        
        Args:
            user: The User object to check
            check_type: Which prerequisite type to check (REQUIRED, RECOMMENDED, COREQUISITE)
            
        Returns:
            Tuple of (bool: all met, list: unmet prerequisite info)
        """
        from apps.courses.models import CoursePrerequisite
        from apps.enrollments.models import Enrollment
        
        prerequisites = CoursePrerequisite.objects.filter(
            course=self,
            prerequisite_type=check_type
        ).select_related('prerequisite_course')
        
        unmet = []
        
        for prereq in prerequisites:
            prereq_course = prereq.prerequisite_course
            
            # Get enrollment for the prerequisite course
            try:
                enrollment = Enrollment.objects.get(
                    user=user,
                    course=prereq_course,
                    status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED]
                )
            except Enrollment.DoesNotExist:
                unmet.append({
                    'course': prereq_course,
                    'reason': 'not_enrolled',
                    'required_completion': prereq.minimum_completion_percentage
                })
                continue
            
            # Check completion percentage
            if enrollment.progress < prereq.minimum_completion_percentage:
                unmet.append({
                    'course': prereq_course,
                    'reason': 'not_completed',
                    'current_progress': enrollment.progress,
                    'required_completion': prereq.minimum_completion_percentage
                })
        
        return (len(unmet) == 0, unmet)

    def get_prerequisite_chain(self) -> list:
        """
        Get the ordered chain of prerequisite courses.
        
        Returns a list of courses in the order they should be taken,
        considering all required prerequisites.
        """
        from apps.courses.models import CoursePrerequisite
        
        # Build dependency graph
        all_prereqs = self.get_all_prerequisites(prerequisite_type='REQUIRED', include_indirect=True)
        
        # Topological sort using Kahn's algorithm
        in_degree = {course.id: 0 for course in all_prereqs}
        in_degree[self.id] = 0
        
        graph = {course.id: [] for course in all_prereqs}
        graph[self.id] = []
        
        for course in list(all_prereqs) + [self]:
            prereqs = CoursePrerequisite.objects.filter(
                course=course,
                prerequisite_type='REQUIRED'
            ).values_list('prerequisite_course_id', flat=True)
            
            for prereq_id in prereqs:
                if prereq_id in graph:
                    graph[prereq_id].append(course.id)
                    in_degree[course.id] = in_degree.get(course.id, 0) + 1
        
        # Process nodes with in_degree 0
        queue = [cid for cid, degree in in_degree.items() if degree == 0]
        result = []
        
        while queue:
            current_id = queue.pop(0)
            if current_id != self.id:  # Don't include self in chain
                result.append(current_id)
            
            for dependent_id in graph.get(current_id, []):
                in_degree[dependent_id] -= 1
                if in_degree[dependent_id] == 0:
                    queue.append(dependent_id)
        
        return list(Course.objects.filter(id__in=result).order_by('title'))


class Module(TimestampedModel):
    """Represents a module or section within a Course."""

    course = models.ForeignKey(Course, related_name="modules", on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(
        default=0, help_text="Order of the module within the course"
    )

    def __str__(self):
        return f"{self.title} (Course: {self.course.title})"

    class Meta:
        ordering = ["course", "order", "title"]
        # Ensure order is unique per course if strict ordering is required without gaps
        # unique_together = ('course', 'order')

    def get_all_prerequisites(self, prerequisite_type: str = None, include_indirect: bool = False) -> models.QuerySet:
        """
        Get all prerequisites for this module.
        
        Args:
            prerequisite_type: Filter by type (REQUIRED, RECOMMENDED, COREQUISITE)
            include_indirect: If True, recursively get prerequisites of prerequisites
            
        Returns:
            QuerySet of Module objects that are prerequisites
        """
        from apps.courses.models import ModulePrerequisite
        
        prereq_qs = ModulePrerequisite.objects.filter(module=self)
        if prerequisite_type:
            prereq_qs = prereq_qs.filter(prerequisite_type=prerequisite_type)
        
        direct_prereqs = prereq_qs.values_list('prerequisite_module_id', flat=True)
        
        if not include_indirect:
            return Module.objects.filter(id__in=direct_prereqs)
        
        # Recursively gather all prerequisites
        all_prereq_ids = set(direct_prereqs)
        to_process = list(direct_prereqs)
        
        while to_process:
            current_id = to_process.pop(0)
            indirect_prereqs = ModulePrerequisite.objects.filter(
                module_id=current_id
            )
            if prerequisite_type:
                indirect_prereqs = indirect_prereqs.filter(prerequisite_type=prerequisite_type)
            
            for prereq_id in indirect_prereqs.values_list('prerequisite_module_id', flat=True):
                if prereq_id not in all_prereq_ids:
                    all_prereq_ids.add(prereq_id)
                    to_process.append(prereq_id)
        
        return Module.objects.filter(id__in=all_prereq_ids)

    def are_prerequisites_met(self, user, check_type: str = 'REQUIRED') -> tuple[bool, list]:
        """
        Check if a user has met all prerequisites for this module.
        
        Args:
            user: The User object to check
            check_type: Which prerequisite type to check (REQUIRED, RECOMMENDED, COREQUISITE)
            
        Returns:
            Tuple of (bool: all met, list: unmet prerequisite info)
        """
        from apps.courses.models import ModulePrerequisite
        from apps.enrollments.models import Enrollment, LearnerProgress
        
        prerequisites = ModulePrerequisite.objects.filter(
            module=self,
            prerequisite_type=check_type
        ).select_related('prerequisite_module')
        
        unmet = []
        
        for prereq in prerequisites:
            prereq_module = prereq.prerequisite_module
            
            # Get enrollment for the prerequisite module's course
            try:
                enrollment = Enrollment.objects.get(
                    user=user,
                    course=prereq_module.course,
                    status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED]
                )
            except Enrollment.DoesNotExist:
                unmet.append({
                    'module': prereq_module,
                    'reason': 'not_enrolled',
                    'required_score': prereq.minimum_score
                })
                continue
            
            # Calculate module completion percentage
            total_required_items = prereq_module.content_items.filter(
                is_required=True, is_published=True
            ).count()
            
            if total_required_items == 0:
                # Module has no required content - consider it completable
                continue
            
            completed_items = LearnerProgress.objects.filter(
                enrollment=enrollment,
                content_item__module=prereq_module,
                content_item__is_required=True,
                content_item__is_published=True,
                status=LearnerProgress.Status.COMPLETED
            ).count()
            
            completion_percentage = (completed_items / total_required_items) * 100
            
            # Check minimum score if specified
            if prereq.minimum_score is not None:
                # Get average score from assessments in this module
                scores = LearnerProgress.objects.filter(
                    enrollment=enrollment,
                    content_item__module=prereq_module,
                    content_item__content_type='QUIZ',
                    status=LearnerProgress.Status.COMPLETED
                ).values_list('progress_details', flat=True)
                
                avg_score = 0
                score_count = 0
                for details in scores:
                    if isinstance(details, dict) and 'score' in details:
                        avg_score += details['score']
                        score_count += 1
                
                if score_count > 0:
                    avg_score = avg_score / score_count
                
                if avg_score < prereq.minimum_score:
                    unmet.append({
                        'module': prereq_module,
                        'reason': 'score_not_met',
                        'current_score': avg_score,
                        'required_score': prereq.minimum_score
                    })
                    continue
            
            # Check completion (100% required)
            if completion_percentage < 100:
                unmet.append({
                    'module': prereq_module,
                    'reason': 'not_completed',
                    'completion_percentage': completion_percentage
                })
        
        return (len(unmet) == 0, unmet)


class ContentItem(TimestampedModel):
    """Represents a piece of learning content within a Module."""

    class ContentType(models.TextChoices):
        # Basic Types
        TEXT = "TEXT", _("Text")  # Simple markdown/HTML content stored directly
        DOCUMENT = "DOCUMENT", _(
            "Document"
        )  # PDF, DOCX, PPTX etc. (linked to File model)
        IMAGE = "IMAGE", _("Image")  # JPG, PNG, GIF etc. (linked to File model)
        VIDEO = "VIDEO", _(
            "Video"
        )  # MP4, WEBM etc. or external link (e.g., YouTube, Vimeo)
        AUDIO = "AUDIO", _("Audio")  # MP3, OGG etc. (linked to File model)
        URL = "URL", _("External URL")  # Link to an external resource

        # Interactive Types (Placeholders - require more complex handling/rendering)
        H5P = "H5P", _("H5P Content")  # Link to H5P file or platform
        SCORM = "SCORM", _(
            "SCORM Package"
        )  # Link to SCORM file (requires SCORM player)
        QUIZ = "QUIZ", _("Quiz / Assessment")  # Link to an Assessment model instance
        # Add other types like simulations, coding exercises, discussions etc.

    module = models.ForeignKey(
        Module, related_name="content_items", on_delete=models.CASCADE
    )
    title = models.CharField(max_length=255)
    content_type = models.CharField(max_length=20, choices=ContentType.choices)
    order = models.PositiveIntegerField(
        default=0, help_text="Order of the content within the module"
    )

    # --- Content Data ---
    # Store content based on type. Use only one of the following.

    # 1. For TEXT type:
    text_content = models.TextField(
        blank=True, null=True, help_text="Markdown or HTML content"
    )

    # 2. For URL type or external video/audio:
    external_url = models.URLField(
        max_length=2048, blank=True, null=True, help_text="URL for external content"
    )

    # 3. For DOCUMENT, IMAGE, VIDEO, AUDIO, H5P, SCORM types (link to File model):
    file = models.ForeignKey(
        'files.File',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='content_items',
        help_text="Associated file for document, media, or package types"
    )

    # 4. For QUIZ type (link to Assessment model):
    # Need to define Assessment model in assessments app first
    # assessment = models.ForeignKey(
    #     'assessments.Assessment',
    #     on_delete=models.SET_NULL, # Keep content item if assessment deleted?
    #     null=True, blank=True,
    #     related_name='content_items',
    #     help_text="Associated assessment for quiz types"
    # )

    # Additional metadata (optional)
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Type-specific metadata (e.g., video duration, quiz settings)",
    )
    is_published = models.BooleanField(
        default=False, db_index=True
    )  # Allow draft content items
    is_required = models.BooleanField(
        default=True,
        help_text="Whether this content item is required for course completion"
    )

    def __str__(self):
        return f"{self.title} ({self.get_content_type_display()})"

    class Meta:
        ordering = ["module", "order", "title"]
        # Ensure order is unique per module if strict ordering is required
        # unique_together = ('module', 'order')


class ModulePrerequisite(TimestampedModel):
    """
    Defines prerequisite relationships between modules.
    
    A module can have multiple prerequisites, and each prerequisite can be:
    - REQUIRED: Must be completed before starting this module
    - RECOMMENDED: Suggested but not enforced
    - COREQUISITE: Can be taken together (concurrent requirement)
    """

    class PrerequisiteType(models.TextChoices):
        REQUIRED = "REQUIRED", _("Required")
        RECOMMENDED = "RECOMMENDED", _("Recommended")
        COREQUISITE = "COREQUISITE", _("Corequisite")

    module = models.ForeignKey(
        Module,
        related_name="prerequisites",
        on_delete=models.CASCADE,
        help_text="The module that has the prerequisite requirement"
    )
    prerequisite_module = models.ForeignKey(
        Module,
        related_name="required_for",
        on_delete=models.CASCADE,
        help_text="The module that must be completed first"
    )
    prerequisite_type = models.CharField(
        max_length=15,
        choices=PrerequisiteType.choices,
        default=PrerequisiteType.REQUIRED,
        help_text="Type of prerequisite relationship"
    )
    minimum_score = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Minimum score required in prerequisite module (0-100, null means completion only)"
    )

    def __str__(self):
        return f"{self.module.title} requires {self.prerequisite_module.title} ({self.prerequisite_type})"

    def clean(self):
        from django.core.exceptions import ValidationError
        
        # Prevent self-referential prerequisites
        if self.module_id == self.prerequisite_module_id:
            raise ValidationError("A module cannot be its own prerequisite.")
        
        # Ensure both modules belong to the same course or prerequisite is from a prerequisite course
        if self.module.course_id != self.prerequisite_module.course_id:
            # Check if prerequisite module's course is a prerequisite of this module's course
            from apps.courses.models import CoursePrerequisite
            is_valid_cross_course = CoursePrerequisite.objects.filter(
                course=self.module.course,
                prerequisite_course=self.prerequisite_module.course
            ).exists()
            if not is_valid_cross_course:
                raise ValidationError(
                    "Prerequisite module must be from the same course or from a prerequisite course."
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    class Meta:
        unique_together = ('module', 'prerequisite_module')
        ordering = ['module', 'prerequisite_type', 'prerequisite_module__order']
        verbose_name = "Module Prerequisite"
        verbose_name_plural = "Module Prerequisites"


class CoursePrerequisite(TimestampedModel):
    """
    Defines prerequisite relationships between courses.
    
    A course can have multiple prerequisites, and each prerequisite can be:
    - REQUIRED: Must be completed before enrolling in this course
    - RECOMMENDED: Suggested but not enforced
    - COREQUISITE: Can be taken together (concurrent enrollment allowed)
    """

    class PrerequisiteType(models.TextChoices):
        REQUIRED = "REQUIRED", _("Required")
        RECOMMENDED = "RECOMMENDED", _("Recommended")
        COREQUISITE = "COREQUISITE", _("Corequisite")

    course = models.ForeignKey(
        Course,
        related_name="prerequisites",
        on_delete=models.CASCADE,
        help_text="The course that has the prerequisite requirement"
    )
    prerequisite_course = models.ForeignKey(
        Course,
        related_name="required_for",
        on_delete=models.CASCADE,
        help_text="The course that must be completed first"
    )
    prerequisite_type = models.CharField(
        max_length=15,
        choices=PrerequisiteType.choices,
        default=PrerequisiteType.REQUIRED,
        help_text="Type of prerequisite relationship"
    )
    minimum_completion_percentage = models.PositiveIntegerField(
        default=100,
        help_text="Minimum completion percentage required (0-100)"
    )

    def __str__(self):
        return f"{self.course.title} requires {self.prerequisite_course.title} ({self.prerequisite_type})"

    def clean(self):
        from django.core.exceptions import ValidationError
        
        # Prevent self-referential prerequisites
        if self.course_id == self.prerequisite_course_id:
            raise ValidationError("A course cannot be its own prerequisite.")
        
        # Ensure both courses belong to the same tenant
        if self.course.tenant_id != self.prerequisite_course.tenant_id:
            raise ValidationError("Prerequisite course must belong to the same tenant.")
        
        # Check for circular dependencies
        if self._creates_circular_dependency():
            raise ValidationError(
                f"Adding this prerequisite would create a circular dependency."
            )

    def _creates_circular_dependency(self):
        """Check if adding this prerequisite creates a circular dependency."""
        visited = set()
        
        def has_cycle(course_id, target_id):
            if course_id == target_id:
                return True
            if course_id in visited:
                return False
            visited.add(course_id)
            
            # Get all prerequisites of this course
            prereqs = CoursePrerequisite.objects.filter(
                course_id=course_id
            ).values_list('prerequisite_course_id', flat=True)
            
            for prereq_id in prereqs:
                if has_cycle(prereq_id, target_id):
                    return True
            return False
        
        # Check if the prerequisite course (or any of its prerequisites) 
        # eventually leads back to the current course
        return has_cycle(self.prerequisite_course_id, self.course_id)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    class Meta:
        unique_together = ('course', 'prerequisite_course')
        ordering = ['course', 'prerequisite_type', 'prerequisite_course__title']
        verbose_name = "Course Prerequisite"
        verbose_name_plural = "Course Prerequisites"


class ContentVersion(TimestampedModel):
    """Tracks versions of a ContentItem."""

    content_item = models.ForeignKey(
        ContentItem, related_name="versions", on_delete=models.CASCADE
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="User who created this version",
    )
    version_number = models.PositiveIntegerField(default=1)
    comment = models.TextField(
        blank=True, help_text="Optional comment about changes in this version"
    )

    # Store snapshot of the content data at the time of versioning
    # This duplicates data but ensures historical accuracy
    content_type = models.CharField(
        max_length=20, choices=ContentItem.ContentType.choices
    )
    text_content = models.TextField(blank=True, null=True)
    external_url = models.URLField(max_length=2048, blank=True, null=True)
    # file_version = models.ForeignKey( # Link to specific FileVersion if using File versions
    #     'files.FileVersion',
    #     on_delete=models.SET_NULL, null=True, blank=True
    # )
    # assessment_snapshot = models.JSONField(default=dict, blank=True) # Snapshot of linked assessment?
    metadata = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.content_item.title} - v{self.version_number}"

    class Meta:
        ordering = ["content_item", "-version_number"]
        unique_together = ("content_item", "version_number")
