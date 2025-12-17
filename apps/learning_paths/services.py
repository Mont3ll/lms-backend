import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from django.db import transaction
from django.db.models import QuerySet, Q
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from apps.courses.models import Course, Module
from apps.enrollments.models import Enrollment
from apps.skills.models import Skill, ModuleSkill, LearnerSkillProgress
from apps.users.models import User

from .models import (
    LearningPath, LearningPathStep, LearningPathProgress, LearningPathStepProgress,
    PersonalizedLearningPath, PersonalizedPathStep, PersonalizedPathProgress
)

logger = logging.getLogger(__name__)


class LearningPathService:
    """Service for managing learning path progress and synchronization."""

    @staticmethod
    @transaction.atomic
    def enroll_in_learning_path(user: User, learning_path: LearningPath) -> tuple[LearningPathProgress, bool, list[Enrollment]]:
        """
        Enrolls a user in a learning path and automatically enrolls them in all courses within the path.
        
        This is the main entry point for learning path enrollment, ensuring that:
        1. A LearningPathProgress record is created/retrieved for the user
        2. LearningPathStepProgress records are created for each step
        3. The user is automatically enrolled in all courses within the path
        
        Args:
            user: The user to enroll
            learning_path: The learning path to enroll in
            
        Returns:
            Tuple of (progress, was_created, course_enrollments)
            - progress: The LearningPathProgress instance
            - was_created: True if progress was newly created, False if it already existed
            - course_enrollments: List of Enrollment objects created/retrieved for the courses
        """
        # Get or create learning path progress
        progress, created = LearningPathProgress.objects.get_or_create(
            user=user,
            learning_path=learning_path,
            defaults={
                'status': LearningPathProgress.Status.NOT_STARTED,
                'current_step_order': 0
            }
        )
        
        # Initialize step progress for all steps
        steps = learning_path.steps.all().order_by('order')
        for step in steps:
            LearningPathStepProgress.objects.get_or_create(
                user=user,
                learning_path_progress=progress,
                step=step,
                defaults={'status': LearningPathStepProgress.Status.NOT_STARTED}
            )
        
        # Auto-enroll user in all courses within the learning path
        course_enrollments = LearningPathService._auto_enroll_in_courses(user, learning_path)
        
        # Sync any existing course completions with the learning path progress
        LearningPathService._sync_existing_course_completions(user, progress)
        
        logger.info(
            f"User {user.id} enrolled in learning path '{learning_path.title}' "
            f"(created={created}, courses_enrolled={len(course_enrollments)})"
        )
        
        return progress, created, course_enrollments
    
    @staticmethod
    def _auto_enroll_in_courses(user: User, learning_path: LearningPath) -> list[Enrollment]:
        """
        Auto-enrolls a user in all courses within a learning path.
        
        Returns a list of Enrollment objects (both newly created and existing).
        
        Note: If a user already has an enrollment (in any status including COMPLETED),
        the existing enrollment is returned WITHOUT modifying its status.
        This preserves course completion status.
        """
        from apps.enrollments.services import EnrollmentService
        
        course_content_type = ContentType.objects.get_for_model(Course)
        enrollments = []
        
        # Get all steps that reference courses (not modules)
        course_steps = learning_path.steps.filter(
            content_type=course_content_type
        ).select_related('content_type')
        
        for step in course_steps:
            try:
                course = Course.objects.get(pk=step.object_id)
                
                # Skip if user's tenant doesn't match course tenant (shouldn't happen normally)
                if not user.is_superuser and user.tenant != course.tenant:
                    logger.warning(
                        f"Skipping auto-enrollment for user {user.id} in course {course.id} - tenant mismatch"
                    )
                    continue
                
                # Check if user already has an enrollment in any status
                existing_enrollment = Enrollment.objects.filter(
                    user=user,
                    course=course
                ).first()
                
                if existing_enrollment:
                    # User already enrolled - preserve existing enrollment status
                    enrollments.append(existing_enrollment)
                    logger.debug(
                        f"User {user.id} already enrolled in course '{course.title}' "
                        f"with status {existing_enrollment.status} (learning path: '{learning_path.title}')"
                    )
                else:
                    # Create new enrollment with ACTIVE status
                    enrollment, _ = EnrollmentService.enroll_user(
                        user=user,
                        course=course,
                        status=Enrollment.Status.ACTIVE
                    )
                    enrollments.append(enrollment)
                    logger.info(
                        f"Auto-enrolled user {user.id} in course '{course.title}' "
                        f"as part of learning path '{learning_path.title}'"
                    )
                    
            except Course.DoesNotExist:
                logger.warning(
                    f"Course {step.object_id} referenced in learning path step {step.id} does not exist"
                )
            except Exception as e:
                logger.error(
                    f"Error auto-enrolling user {user.id} in course {step.object_id}: {e}",
                    exc_info=True
                )
        
        return enrollments
    
    @staticmethod
    def _sync_existing_course_completions(user: User, progress: LearningPathProgress) -> None:
        """
        Syncs existing course completions with learning path progress.
        
        This handles the case where a user:
        1. Was already enrolled in some courses before starting the learning path
        2. Had already completed some courses
        
        In this case, we mark the corresponding learning path steps as completed.
        """
        learning_path = progress.learning_path
        course_content_type = ContentType.objects.get_for_model(Course)
        
        # Get all course steps in the learning path
        course_steps = learning_path.steps.filter(
            content_type=course_content_type
        )
        
        for step in course_steps:
            # Check if user has a completed enrollment for this course
            completed_enrollment = Enrollment.objects.filter(
                user=user,
                course_id=step.object_id,
                status=Enrollment.Status.COMPLETED
            ).first()
            
            if completed_enrollment:
                # Get or create step progress and mark as completed
                step_progress, _ = LearningPathStepProgress.objects.get_or_create(
                    user=user,
                    learning_path_progress=progress,
                    step=step,
                    defaults={
                        'status': LearningPathStepProgress.Status.COMPLETED,
                        'started_at': completed_enrollment.enrolled_at,
                        'completed_at': completed_enrollment.completed_at
                    }
                )
                
                # If step progress already existed but wasn't completed, update it
                if step_progress.status != LearningPathStepProgress.Status.COMPLETED:
                    step_progress.status = LearningPathStepProgress.Status.COMPLETED
                    step_progress.completed_at = completed_enrollment.completed_at
                    if not step_progress.started_at:
                        step_progress.started_at = completed_enrollment.enrolled_at
                    step_progress.save(update_fields=['status', 'completed_at', 'started_at', 'updated_at'])
                    
                    logger.info(
                        f"Synced existing course completion: user {user.id}, "
                        f"course {step.object_id}, learning path step {step.id}"
                    )
        
        # Update the overall learning path progress based on completed steps
        LearningPathService._update_learning_path_progress(progress)

    @staticmethod
    @transaction.atomic
    def sync_course_completion_with_learning_paths(enrollment: Enrollment) -> bool:
        """
        Synchronizes course completion with learning path progress.
        Called when a course enrollment is marked as completed.
        
        Returns True if any learning path progress was updated.
        """
        if enrollment.status != Enrollment.Status.COMPLETED:
            return False

        course = enrollment.course
        user = enrollment.user
        course_content_type = ContentType.objects.get_for_model(Course)
        
        # Find all learning path steps that reference this course
        learning_path_steps = LearningPathStep.objects.filter(
            content_type=course_content_type,
            object_id=course.id,
            learning_path__tenant=course.tenant,  # Ensure tenant consistency
            learning_path__status=LearningPath.Status.PUBLISHED
        ).select_related('learning_path')

        updated_paths = []
        
        for step in learning_path_steps:
            learning_path = step.learning_path
            
            # Get or create learning path progress for this user
            path_progress, created = LearningPathProgress.objects.get_or_create(
                user=user,
                learning_path=learning_path,
                defaults={
                    'status': LearningPathProgress.Status.NOT_STARTED,
                    'current_step_order': 0
                }
            )
            
            # Get or create step progress for this specific step
            step_progress, step_created = LearningPathStepProgress.objects.get_or_create(
                user=user,
                learning_path_progress=path_progress,
                step=step,
                defaults={
                    'status': LearningPathStepProgress.Status.NOT_STARTED
                }
            )
            
            # Mark step as completed if not already completed
            if step_progress.status != LearningPathStepProgress.Status.COMPLETED:
                step_progress.status = LearningPathStepProgress.Status.COMPLETED
                step_progress.completed_at = timezone.now()
                if not step_progress.started_at:
                    step_progress.started_at = step_progress.completed_at
                step_progress.save(update_fields=['status', 'completed_at', 'started_at', 'updated_at'])
                
                logger.info(
                    f"Marked learning path step {step.id} as completed for user {user.id} "
                    f"due to course {course.id} completion"
                )
            
            # Update overall learning path progress
            LearningPathService._update_learning_path_progress(path_progress)
            updated_paths.append(learning_path.id)

        if updated_paths:
            logger.info(
                f"Updated learning path progress for user {user.id} in paths: {updated_paths} "
                f"due to course {course.id} completion"
            )
            return True
            
        return False

    @staticmethod
    @transaction.atomic 
    def _update_learning_path_progress(path_progress: LearningPathProgress) -> None:
        """
        Updates the overall learning path progress based on completed steps.
        """
        learning_path = path_progress.learning_path
        user = path_progress.user
        
        # Get all steps in this learning path
        all_steps = learning_path.steps.all().order_by('order')
        total_steps = all_steps.count()
        
        if total_steps == 0:
            # No steps, mark as completed
            if path_progress.status != LearningPathProgress.Status.COMPLETED:
                path_progress.status = LearningPathProgress.Status.COMPLETED
                path_progress.completed_at = timezone.now()
                path_progress.current_step_order = 0
                path_progress.save(update_fields=['status', 'completed_at', 'current_step_order', 'updated_at'])
            return

        # Count completed steps
        completed_steps = LearningPathStepProgress.objects.filter(
            user=user,
            learning_path_progress=path_progress,
            status=LearningPathStepProgress.Status.COMPLETED
        ).count()

        # Update progress status and current step
        updated = False
        
        if completed_steps >= total_steps:
            # All steps completed
            if path_progress.status != LearningPathProgress.Status.COMPLETED:
                path_progress.status = LearningPathProgress.Status.COMPLETED
                path_progress.completed_at = timezone.now()
                path_progress.current_step_order = total_steps  # Set to last step order
                updated = True
        elif completed_steps > 0:
            # Some steps completed
            if path_progress.status == LearningPathProgress.Status.NOT_STARTED:
                path_progress.status = LearningPathProgress.Status.IN_PROGRESS
                path_progress.started_at = timezone.now()
                updated = True
            elif path_progress.status != LearningPathProgress.Status.IN_PROGRESS:
                path_progress.status = LearningPathProgress.Status.IN_PROGRESS
                updated = True
            
            # Update current step order to the highest completed step
            highest_completed_step = LearningPathStepProgress.objects.filter(
                user=user,
                learning_path_progress=path_progress,
                status=LearningPathStepProgress.Status.COMPLETED
            ).select_related('step').order_by('-step__order').first()
            
            if highest_completed_step and path_progress.current_step_order != highest_completed_step.step.order:
                path_progress.current_step_order = highest_completed_step.step.order
                updated = True

        if updated:
            path_progress.save(update_fields=[
                'status', 'started_at', 'completed_at', 'current_step_order', 'updated_at'
            ])
            logger.info(
                f"Updated learning path progress {path_progress.id}: "
                f"status={path_progress.status}, completed_steps={completed_steps}/{total_steps}"
            )

    @staticmethod
    def sync_course_enrollment_with_learning_paths(enrollment: Enrollment) -> bool:
        """
        Synchronizes course enrollment status changes with learning path progress.
        This can handle both completion and un-completion scenarios.
        
        Returns True if any learning path progress was updated.
        """
        if enrollment.status == Enrollment.Status.COMPLETED:
            return LearningPathService.sync_course_completion_with_learning_paths(enrollment)
        elif enrollment.status == Enrollment.Status.ACTIVE:
            # Handle case where a completed course is reverted to active
            # (e.g., if new content is added after completion)
            return LearningPathService._sync_course_incompletion_with_learning_paths(enrollment)
        
        return False
    
    @staticmethod
    @transaction.atomic
    def _sync_course_incompletion_with_learning_paths(enrollment: Enrollment) -> bool:
        """
        Handle case where a previously completed course is no longer complete.
        This reverts learning path step progress if needed.
        """
        course = enrollment.course
        user = enrollment.user
        course_content_type = ContentType.objects.get_for_model(Course)
        
        # Find all learning path steps that reference this course
        learning_path_steps = LearningPathStep.objects.filter(
            content_type=course_content_type,
            object_id=course.id,
            learning_path__tenant=course.tenant
        ).select_related('learning_path')

        updated_paths = []
        
        for step in learning_path_steps:
            # Find step progress for this step
            try:
                step_progress = LearningPathStepProgress.objects.get(
                    user=user,
                    step=step
                )
                
                # If step was completed but course is no longer complete, revert step
                if step_progress.status == LearningPathStepProgress.Status.COMPLETED:
                    step_progress.status = LearningPathStepProgress.Status.IN_PROGRESS
                    step_progress.completed_at = None
                    step_progress.save(update_fields=['status', 'completed_at', 'updated_at'])
                    
                    # Update the overall learning path progress
                    path_progress = step_progress.learning_path_progress
                    LearningPathService._update_learning_path_progress(path_progress)
                    updated_paths.append(step.learning_path.id)
                    
                    logger.info(
                        f"Reverted learning path step {step.id} completion for user {user.id} "
                        f"due to course {course.id} no longer being complete"
                    )
                    
            except LearningPathStepProgress.DoesNotExist:
                pass  # No step progress exists, nothing to revert

        return len(updated_paths) > 0


@dataclass
class SkillGap:
    """Represents a gap between current and target skill proficiency."""
    skill: Skill
    current_score: int
    target_score: int
    gap: int  # target_score - current_score
    
    @property
    def priority(self) -> int:
        """Higher gap = higher priority."""
        return self.gap


@dataclass
class ModuleCandidate:
    """A module being considered for inclusion in a personalized path."""
    module: Module
    skills_addressed: list[Skill]
    total_skill_contribution: int  # Sum of proficiency gains across all skills
    estimated_duration: int  # in minutes
    prerequisite_modules: list[Module]
    contribution_level: str
    difficulty_order: int = 2  # 1=beginner, 2=intermediate, 3=advanced
    
    @property
    def efficiency_score(self) -> float:
        """Score based on skill contribution per time unit."""
        if self.estimated_duration == 0:
            return 0.0
        return self.total_skill_contribution / self.estimated_duration


class PersonalizedPathGenerator:
    """
    Service for generating personalized learning paths based on skill gaps.
    
    The generator analyzes a user's current skill proficiencies against
    target skills and creates an optimized learning path using available
    modules in the tenant's course catalog.
    
    Generation Strategies:
    - SKILL_GAP: Fill gaps between current and target proficiency levels
    - REMEDIAL: Focus on skills where the user is struggling
    - GOAL_BASED: Work towards specific skill targets
    - ONBOARDING: Introduction to a role or domain
    """
    
    # Default configuration
    DEFAULT_TARGET_PROFICIENCY = 70  # Intermediate level
    DEFAULT_PATH_EXPIRY_DAYS = 90
    MIN_SKILL_GAP_TO_INCLUDE = 10  # Don't include skills with gap < 10
    MAX_MODULES_PER_PATH = 20
    
    # Difficulty preference options
    DIFFICULTY_ANY = 'ANY'
    DIFFICULTY_BEGINNER = 'BEGINNER'
    DIFFICULTY_INTERMEDIATE = 'INTERMEDIATE'
    DIFFICULTY_ADVANCED = 'ADVANCED'
    DIFFICULTY_PROGRESSIVE = 'PROGRESSIVE'  # Start easy, progress to harder
    
    def __init__(
        self,
        user: User,
        tenant,
        target_skills: QuerySet | list[Skill] | None = None,
        generation_type: str = PersonalizedLearningPath.GenerationType.SKILL_GAP,
        target_proficiency: int = DEFAULT_TARGET_PROFICIENCY,
        max_modules: int = MAX_MODULES_PER_PATH,
        include_completed_modules: bool = False,
        difficulty_preference: str = DIFFICULTY_ANY
    ):
        """
        Initialize the path generator.
        
        Args:
            user: The user to generate a path for
            tenant: The tenant context
            target_skills: Specific skills to target (if None, analyzes all user skill gaps)
            generation_type: Type of path generation strategy
            target_proficiency: Target proficiency score (0-100)
            max_modules: Maximum number of modules to include
            include_completed_modules: Whether to include modules the user has already completed
            difficulty_preference: Filter modules by difficulty level (ANY, BEGINNER, 
                                   INTERMEDIATE, ADVANCED, or PROGRESSIVE for gradual increase)
        """
        self.user = user
        self.tenant = tenant
        self.target_skills = list(target_skills) if target_skills else []
        self.generation_type = generation_type
        self.target_proficiency = target_proficiency
        self.max_modules = max_modules
        self.include_completed_modules = include_completed_modules
        self.difficulty_preference = difficulty_preference
    
    @transaction.atomic
    def generate(self, title: str | None = None, description: str | None = None) -> PersonalizedLearningPath:
        """
        Generate a personalized learning path for the user.
        
        Args:
            title: Optional custom title (auto-generated if not provided)
            description: Optional custom description (auto-generated if not provided)
            
        Returns:
            PersonalizedLearningPath instance with steps
            
        Raises:
            ValueError: If no skills to target or no modules available
        """
        logger.info(f"Generating personalized path for user {self.user.id} ({self.generation_type})")
        
        # Step 1: Identify skill gaps
        skill_gaps = self._analyze_skill_gaps()
        if not skill_gaps:
            raise ValueError("No skill gaps found to address. User may already be proficient in all target skills.")
        
        logger.debug(f"Found {len(skill_gaps)} skill gaps to address")
        
        # Step 2: Find candidate modules
        module_candidates = self._find_module_candidates(skill_gaps)
        if not module_candidates:
            raise ValueError("No modules found that address the identified skill gaps.")
        
        logger.debug(f"Found {len(module_candidates)} candidate modules")
        
        # Step 3: Select and order modules
        selected_modules = self._select_optimal_modules(module_candidates, skill_gaps)
        if not selected_modules:
            raise ValueError("Could not select any modules for the learning path.")
        
        logger.debug(f"Selected {len(selected_modules)} modules for path")
        
        # Step 4: Create the learning path
        path = self._create_path(selected_modules, skill_gaps, title, description)
        
        logger.info(
            f"Generated personalized path '{path.title}' with {path.steps.count()} steps "
            f"for user {self.user.id}"
        )
        
        return path
    
    def _analyze_skill_gaps(self) -> list[SkillGap]:
        """
        Analyze the user's skill gaps relative to target proficiency.
        
        Returns:
            List of SkillGap objects sorted by gap size (largest first)
        """
        skill_gaps = []
        
        # Get skills to analyze
        skills_to_analyze = self.target_skills if self.target_skills else self._get_all_relevant_skills()
        
        for skill in skills_to_analyze:
            # Get user's current proficiency
            try:
                progress = LearnerSkillProgress.objects.get(user=self.user, skill=skill)
                current_score = progress.proficiency_score
            except LearnerSkillProgress.DoesNotExist:
                current_score = 0
            
            gap = self.target_proficiency - current_score
            
            # Only include if gap is significant
            if gap >= self.MIN_SKILL_GAP_TO_INCLUDE:
                skill_gaps.append(SkillGap(
                    skill=skill,
                    current_score=current_score,
                    target_score=self.target_proficiency,
                    gap=gap
                ))
        
        # Sort by gap size (largest gaps first = highest priority)
        skill_gaps.sort(key=lambda g: g.priority, reverse=True)
        
        return skill_gaps
    
    def _get_all_relevant_skills(self) -> list[Skill]:
        """Get all active skills in the tenant that have module mappings."""
        return list(
            Skill.objects.filter(
                tenant=self.tenant,
                is_active=True,
                module_mappings__module__course__tenant=self.tenant,
                module_mappings__module__course__status='PUBLISHED'
            ).distinct()
        )
    
    def _get_difficulty_filter(self) -> Q | None:
        """
        Get the difficulty filter Q object based on difficulty_preference.
        
        Returns:
            Q object for filtering, or None if no filtering needed
        """
        from apps.courses.models import Course
        
        difficulty_map = {
            self.DIFFICULTY_BEGINNER: Course.DifficultyLevel.BEGINNER,
            self.DIFFICULTY_INTERMEDIATE: Course.DifficultyLevel.INTERMEDIATE,
            self.DIFFICULTY_ADVANCED: Course.DifficultyLevel.ADVANCED,
        }
        
        if self.difficulty_preference in difficulty_map:
            return Q(module__course__difficulty_level=difficulty_map[self.difficulty_preference])
        
        # For ANY or PROGRESSIVE, no initial filtering
        return None
    
    def _get_difficulty_order(self, module: Module) -> int:
        """
        Get a numeric order for module difficulty (for PROGRESSIVE mode sorting).
        
        Lower numbers = easier modules (should come first in progressive mode).
        
        Returns:
            Integer representing difficulty order (1=beginner, 2=intermediate, 3=advanced)
        """
        from apps.courses.models import Course
        
        difficulty_order = {
            Course.DifficultyLevel.BEGINNER: 1,
            Course.DifficultyLevel.INTERMEDIATE: 2,
            Course.DifficultyLevel.ADVANCED: 3,
        }
        
        course_difficulty = getattr(module.course, 'difficulty_level', Course.DifficultyLevel.BEGINNER)
        return difficulty_order.get(course_difficulty, 2)  # Default to intermediate
    
    def _find_module_candidates(self, skill_gaps: list[SkillGap]) -> list[ModuleCandidate]:
        """
        Find modules that address the identified skill gaps.
        
        Args:
            skill_gaps: List of skill gaps to address
            
        Returns:
            List of ModuleCandidate objects
        """
        skill_ids = [gap.skill.id for gap in skill_gaps]
        skill_map = {gap.skill.id: gap for gap in skill_gaps}
        
        # Build base query for module-skill mappings
        module_skills_query = ModuleSkill.objects.filter(
            skill_id__in=skill_ids,
            module__course__tenant=self.tenant,
            module__course__status='PUBLISHED'
        )
        
        # Apply difficulty filter if specified (not for ANY or PROGRESSIVE)
        difficulty_filter = self._get_difficulty_filter()
        if difficulty_filter:
            module_skills_query = module_skills_query.filter(difficulty_filter)
        
        # Execute query with related objects
        module_skills = module_skills_query.select_related('module', 'skill', 'module__course')
        
        # Group by module
        module_data: dict[str, dict] = {}
        
        for ms in module_skills:
            module_id = str(ms.module.id)
            
            if module_id not in module_data:
                module_data[module_id] = {
                    'module': ms.module,
                    'skills': [],
                    'total_contribution': 0,
                    'contribution_level': ms.contribution_level
                }
            
            module_data[module_id]['skills'].append(ms.skill)
            module_data[module_id]['total_contribution'] += ms.proficiency_gained
            
            # Track highest contribution level
            level_priority = {
                ModuleSkill.ContributionLevel.INTRODUCES: 1,
                ModuleSkill.ContributionLevel.DEVELOPS: 2,
                ModuleSkill.ContributionLevel.REINFORCES: 3,
                ModuleSkill.ContributionLevel.MASTERS: 4
            }
            current_level = module_data[module_id]['contribution_level']
            if level_priority.get(ms.contribution_level, 0) > level_priority.get(current_level, 0):
                module_data[module_id]['contribution_level'] = ms.contribution_level
        
        # Filter out completed modules if needed
        if not self.include_completed_modules:
            completed_module_ids = self._get_completed_module_ids()
            module_data = {
                mid: data for mid, data in module_data.items()
                if mid not in completed_module_ids
            }
        
        # Create candidates
        candidates = []
        for module_id, data in module_data.items():
            module = data['module']
            
            # Estimate duration (use module's estimated_duration or calculate from content)
            estimated_duration = self._estimate_module_duration(module)
            
            # Get prerequisites
            prerequisites = self._get_module_prerequisites(module)
            
            # Get difficulty order for this module
            difficulty_order = self._get_difficulty_order(module)
            
            candidates.append(ModuleCandidate(
                module=module,
                skills_addressed=data['skills'],
                total_skill_contribution=data['total_contribution'],
                estimated_duration=estimated_duration,
                prerequisite_modules=prerequisites,
                contribution_level=data['contribution_level'],
                difficulty_order=difficulty_order
            ))
        
        return candidates
    
    def _get_completed_module_ids(self) -> set[str]:
        """Get IDs of modules the user has completed."""
        from apps.enrollments.models import LearnerProgress
        
        # A module is complete if all its content items are completed
        completed_module_ids = set()
        
        # Get user's enrollments
        enrollments = Enrollment.objects.filter(
            user=self.user,
            status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED]
        ).select_related('course')
        
        for enrollment in enrollments:
            # Get all modules in the course
            modules = enrollment.course.modules.all()
            
            for module in modules:
                content_count = module.content_items.count()
                if content_count == 0:
                    continue
                
                completed_count = LearnerProgress.objects.filter(
                    enrollment=enrollment,
                    content_item__module=module,
                    status=LearnerProgress.Status.COMPLETED
                ).count()
                
                if completed_count >= content_count:
                    completed_module_ids.add(str(module.id))
        
        return completed_module_ids
    
    def _estimate_module_duration(self, module: Module) -> int:
        """
        Estimate module duration in minutes.
        
        Uses the module's explicit duration if set, otherwise estimates
        based on content items.
        """
        # Check if module has explicit duration
        if hasattr(module, 'estimated_duration') and module.estimated_duration:
            return module.estimated_duration
        
        # Estimate based on content items
        total_minutes = 0
        for content in module.content_items.all():
            if hasattr(content, 'duration') and content.duration:
                total_minutes += content.duration
            else:
                # Default estimates by content type
                type_estimates = {
                    'VIDEO': 10,
                    'DOCUMENT': 15,
                    'ASSESSMENT': 20,
                    'SCORM': 30,
                    'H5P': 15,
                    'IMAGE': 5,
                    'LINK': 10
                }
                content_type = getattr(content, 'content_type', 'DOCUMENT')
                total_minutes += type_estimates.get(content_type, 10)
        
        return max(total_minutes, 10)  # Minimum 10 minutes
    
    def _get_module_prerequisites(self, module: Module) -> list[Module]:
        """Get prerequisite modules for a given module."""
        from apps.courses.models import ModulePrerequisite
        
        prereqs = ModulePrerequisite.objects.filter(
            module=module
        ).select_related('prerequisite_module')
        
        return [prereq.prerequisite_module for prereq in prereqs]
    
    def _create_prerequisite_candidate(self, module: Module) -> ModuleCandidate:
        """
        Create a ModuleCandidate for a prerequisite module that wasn't in the initial candidates.
        
        This is used when a module's prerequisites weren't found in the candidates list
        (e.g., when prerequisite modules don't directly teach target skills but are
        required for modules that do).
        
        Args:
            module: The prerequisite module
            
        Returns:
            A ModuleCandidate for the prerequisite module
        """
        # Get any skills this module teaches
        module_skills = ModuleSkill.objects.filter(module=module).select_related('skill')
        skills_addressed = [ms.skill for ms in module_skills]
        total_contribution = sum(ms.proficiency_gained for ms in module_skills)
        
        # Get the contribution level (use INTRODUCES as default for prerequisites)
        contribution_level = ModuleSkill.ContributionLevel.INTRODUCES
        if module_skills:
            level_priority = {
                ModuleSkill.ContributionLevel.INTRODUCES: 1,
                ModuleSkill.ContributionLevel.DEVELOPS: 2,
                ModuleSkill.ContributionLevel.REINFORCES: 3,
                ModuleSkill.ContributionLevel.MASTERS: 4
            }
            contribution_level = max(
                module_skills,
                key=lambda ms: level_priority.get(ms.contribution_level, 0)
            ).contribution_level
        
        return ModuleCandidate(
            module=module,
            skills_addressed=skills_addressed,
            total_skill_contribution=total_contribution,
            estimated_duration=self._estimate_module_duration(module),
            prerequisite_modules=self._get_module_prerequisites(module),
            contribution_level=contribution_level,
            difficulty_order=self._get_difficulty_order(module)
        )
    
    def _select_optimal_modules(
        self,
        candidates: list[ModuleCandidate],
        skill_gaps: list[SkillGap]
    ) -> list[ModuleCandidate]:
        """
        Select the optimal set of modules to include in the path.
        
        Uses a greedy algorithm that:
        1. Prioritizes modules with high efficiency scores
        2. Ensures skill coverage
        3. Respects prerequisite ordering
        4. Stays within max_modules limit
        5. For PROGRESSIVE mode, prefers easier modules first then gradually harder
        
        Args:
            candidates: Available module candidates
            skill_gaps: Skill gaps to address
            
        Returns:
            Ordered list of selected ModuleCandidate objects
        """
        selected: list[ModuleCandidate] = []
        remaining_gaps = {gap.skill.id: gap.gap for gap in skill_gaps}
        selected_module_ids = set()
        
        # Get completed modules - these count as "satisfied" for prerequisite checking
        # but won't be added to the path (unless include_completed_modules is True)
        completed_module_ids = set()
        if not self.include_completed_modules:
            completed_module_ids = self._get_completed_module_ids()
        
        # Satisfied prerequisites = selected modules + completed modules
        # This set tracks which prerequisites are considered "met"
        satisfied_prereq_ids = completed_module_ids.copy()
        
        # Build a lookup of candidates by module ID for quick access
        candidate_lookup: dict[str, ModuleCandidate] = {
            str(c.module.id): c for c in candidates
        }
        
        # For PROGRESSIVE mode, sort by difficulty first, then efficiency
        # This ensures we prefer easier modules early in the path
        is_progressive = self.difficulty_preference == self.DIFFICULTY_PROGRESSIVE
        
        # Sort candidates based on mode
        sorted_candidates = sorted(candidates, key=lambda c: c.efficiency_score, reverse=True)
        
        while len(selected) < self.max_modules and sorted_candidates:
            # Find the best candidate that addresses remaining gaps
            best_candidate = None
            best_score = -1
            best_difficulty = 999  # For PROGRESSIVE mode tiebreaker
            
            for candidate in sorted_candidates:
                # Skip if already selected
                if str(candidate.module.id) in selected_module_ids:
                    continue
                
                # Check prerequisites are satisfied (either selected or already completed)
                prereq_ids = {str(p.id) for p in candidate.prerequisite_modules}
                if prereq_ids and not prereq_ids.issubset(satisfied_prereq_ids):
                    # Need to add prerequisites first - add the candidate to be considered later
                    continue
                
                # Calculate how much of remaining gaps this module addresses
                gap_contribution = 0
                for skill in candidate.skills_addressed:
                    if skill.id in remaining_gaps and remaining_gaps[skill.id] > 0:
                        gap_contribution += min(
                            remaining_gaps[skill.id],
                            candidate.total_skill_contribution
                        )
                
                # Skip candidates that don't contribute to remaining gaps
                if gap_contribution <= 0:
                    continue
                
                # Score based on gap contribution and efficiency
                score = gap_contribution * candidate.efficiency_score
                
                # For PROGRESSIVE mode, primary sort is by difficulty (easier first)
                # Only use score as tiebreaker for same-difficulty modules
                if is_progressive:
                    # Compare by difficulty first, then score
                    if candidate.difficulty_order < best_difficulty:
                        # This candidate is easier, prefer it
                        best_score = score
                        best_candidate = candidate
                        best_difficulty = candidate.difficulty_order
                    elif candidate.difficulty_order == best_difficulty and score > best_score:
                        # Same difficulty, prefer higher score
                        best_score = score
                        best_candidate = candidate
                        best_difficulty = candidate.difficulty_order
                else:
                    # Standard mode: prefer higher score
                    if score > best_score:
                        best_score = score
                        best_candidate = candidate
            
            if best_candidate is None:
                # Try adding a prerequisite if any candidates have unmet prerequisites
                added_prereq = False
                for candidate in sorted_candidates:
                    if str(candidate.module.id) in selected_module_ids:
                        continue
                    
                    for prereq in candidate.prerequisite_modules:
                        prereq_id = str(prereq.id)
                        if prereq_id not in satisfied_prereq_ids:
                            # Skip if this prerequisite is already completed (shouldn't add it)
                            if prereq_id in completed_module_ids:
                                # Mark as satisfied and continue
                                satisfied_prereq_ids.add(prereq_id)
                                added_prereq = True
                                break
                            
                            # First try to find the prereq in existing candidates
                            prereq_candidate = candidate_lookup.get(prereq_id)
                            
                            # If not found in candidates, create one from the database
                            if prereq_candidate is None:
                                try:
                                    prereq_candidate = self._create_prerequisite_candidate(prereq)
                                    # Add to lookup for future reference
                                    candidate_lookup[prereq_id] = prereq_candidate
                                except Exception as e:
                                    logger.warning(
                                        f"Could not create candidate for prerequisite module {prereq_id}: {e}"
                                    )
                                    continue
                            
                            selected.append(prereq_candidate)
                            selected_module_ids.add(prereq_id)
                            satisfied_prereq_ids.add(prereq_id)
                            added_prereq = True
                            break
                    if added_prereq:
                        break
                
                if not added_prereq:
                    # No more modules can be added
                    break
            else:
                selected.append(best_candidate)
                selected_module_ids.add(str(best_candidate.module.id))
                satisfied_prereq_ids.add(str(best_candidate.module.id))
                
                # Update remaining gaps
                for skill in best_candidate.skills_addressed:
                    if skill.id in remaining_gaps:
                        # Get the actual proficiency gained for this skill
                        skill_mapping = ModuleSkill.objects.filter(
                            module=best_candidate.module,
                            skill=skill
                        ).first()
                        if skill_mapping:
                            remaining_gaps[skill.id] = max(
                                0,
                                remaining_gaps[skill.id] - skill_mapping.proficiency_gained
                            )
                
                # Remove from candidates list
                sorted_candidates = [c for c in sorted_candidates if str(c.module.id) != str(best_candidate.module.id)]
            
            # Check if all gaps are filled
            if all(gap <= 0 for gap in remaining_gaps.values()):
                break
        
        return selected
    
    def _create_path(
        self,
        selected_modules: list[ModuleCandidate],
        skill_gaps: list[SkillGap],
        title: str | None,
        description: str | None
    ) -> PersonalizedLearningPath:
        """
        Create the PersonalizedLearningPath and its steps.
        
        Args:
            selected_modules: Ordered list of modules to include
            skill_gaps: Original skill gaps being addressed
            title: Custom title (or auto-generated)
            description: Custom description (or auto-generated)
            
        Returns:
            Created PersonalizedLearningPath instance
        """
        # Calculate total estimated duration
        total_minutes = sum(m.estimated_duration for m in selected_modules)
        total_hours = max(1, total_minutes // 60)
        
        # Generate title and description if not provided
        if not title:
            skill_names = [gap.skill.name for gap in skill_gaps[:3]]
            title = f"Learning Path: {', '.join(skill_names)}"
            if len(skill_gaps) > 3:
                title += f" (+{len(skill_gaps) - 3} more)"
        
        if not description:
            description = self._generate_description(skill_gaps, selected_modules)
        
        # Calculate expiry date
        expires_at = timezone.now() + timedelta(days=self.DEFAULT_PATH_EXPIRY_DAYS)
        
        # Store generation parameters
        generation_params = {
            'target_proficiency': self.target_proficiency,
            'skill_gaps_count': len(skill_gaps),
            'target_skill_ids': [str(gap.skill.id) for gap in skill_gaps],
            'include_completed_modules': self.include_completed_modules,
            'max_modules': self.max_modules,
            'difficulty_preference': self.difficulty_preference,
            'generated_at_timestamp': timezone.now().isoformat()
        }
        
        # Create the path
        path = PersonalizedLearningPath.objects.create(
            user=self.user,
            tenant=self.tenant,
            title=title,
            description=description,
            generation_type=self.generation_type,
            estimated_duration=total_hours,
            status=PersonalizedLearningPath.Status.ACTIVE,
            expires_at=expires_at,
            generation_params=generation_params
        )
        
        # Add target skills
        target_skills = [gap.skill for gap in skill_gaps]
        path.target_skills.set(target_skills)
        
        # Create steps
        for order, candidate in enumerate(selected_modules, start=1):
            reason = self._generate_step_reason(candidate, skill_gaps)
            
            step = PersonalizedPathStep.objects.create(
                path=path,
                module=candidate.module,
                order=order,
                is_required=True,
                reason=reason,
                estimated_duration=candidate.estimated_duration
            )
            
            # Link target skills for this step
            step.target_skills.set(candidate.skills_addressed)
        
        # Create initial progress record
        PersonalizedPathProgress.objects.create(
            user=self.user,
            path=path,
            status=PersonalizedPathProgress.Status.NOT_STARTED,
            current_step_order=0
        )
        
        return path
    
    def _generate_description(
        self,
        skill_gaps: list[SkillGap],
        selected_modules: list[ModuleCandidate]
    ) -> str:
        """Generate a description for the learning path."""
        skill_summary = []
        for gap in skill_gaps[:5]:
            skill_summary.append(f"- {gap.skill.name}: {gap.current_score}% → {gap.target_score}%")
        
        description = (
            f"This personalized learning path was generated to help you improve in "
            f"{len(skill_gaps)} skill area(s).\n\n"
            f"Target Skills:\n"
            f"{chr(10).join(skill_summary)}"
        )
        
        if len(skill_gaps) > 5:
            description += f"\n- ...and {len(skill_gaps) - 5} more skills"
        
        total_minutes = sum(m.estimated_duration for m in selected_modules)
        hours = total_minutes // 60
        minutes = total_minutes % 60
        
        description += f"\n\nEstimated time to complete: {hours}h {minutes}m"
        
        return description
    
    def _generate_step_reason(
        self,
        candidate: ModuleCandidate,
        skill_gaps: list[SkillGap]
    ) -> str:
        """Generate a reason for why this module was included."""
        skill_gap_map = {gap.skill.id: gap for gap in skill_gaps}
        
        addressed_gaps = []
        for skill in candidate.skills_addressed:
            if skill.id in skill_gap_map:
                gap = skill_gap_map[skill.id]
                addressed_gaps.append(f"{skill.name} (gap: {gap.gap} points)")
        
        if addressed_gaps:
            reason = f"This module addresses: {', '.join(addressed_gaps[:3])}"
            if len(addressed_gaps) > 3:
                reason += f" and {len(addressed_gaps) - 3} more skill(s)"
        else:
            reason = f"This module is a prerequisite for other modules in this path."
        
        return reason
    
    @staticmethod
    def regenerate_path(
        path: PersonalizedLearningPath,
        preserve_progress: bool = True
    ) -> PersonalizedLearningPath:
        """
        Regenerate a personalized learning path, optionally preserving progress.
        
        This is useful when:
        - New modules have been added to the catalog
        - User's skill levels have changed significantly
        - The path has expired and needs refreshing
        
        Args:
            path: The existing path to regenerate
            preserve_progress: If True, completed steps will be excluded from the new path
            
        Returns:
            New PersonalizedLearningPath instance
        """
        # Get generation params from the original path
        params = path.generation_params or {}
        
        # Get target skills
        target_skills = list(path.target_skills.all())
        
        # Create generator with same parameters
        generator = PersonalizedPathGenerator(
            user=path.user,
            tenant=path.tenant,
            target_skills=target_skills,
            generation_type=path.generation_type,
            target_proficiency=params.get('target_proficiency', PersonalizedPathGenerator.DEFAULT_TARGET_PROFICIENCY),
            max_modules=params.get('max_modules', PersonalizedPathGenerator.MAX_MODULES_PER_PATH),
            include_completed_modules=not preserve_progress,
            difficulty_preference=params.get('difficulty_preference', PersonalizedPathGenerator.DIFFICULTY_ANY)
        )
        
        # Archive the old path
        path.status = PersonalizedLearningPath.Status.ARCHIVED
        path.save(update_fields=['status', 'updated_at'])
        
        # Generate new path
        new_path = generator.generate(
            title=f"{path.title} (Regenerated)",
            description=None  # Generate fresh description
        )
        
        logger.info(f"Regenerated path {path.id} as {new_path.id} for user {path.user.id}")
        
        return new_path
