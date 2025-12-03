import logging
from typing import Optional

from django.db import transaction
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from apps.courses.models import Course
from apps.enrollments.models import Enrollment
from apps.users.models import User

from .models import LearningPath, LearningPathStep, LearningPathProgress, LearningPathStepProgress

logger = logging.getLogger(__name__)


class LearningPathService:
    """Service for managing learning path progress and synchronization."""

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
