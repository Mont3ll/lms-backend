"""
Signal handlers for the Learning Paths app.

Handles automatic remedial path suggestions when:
- A user fails an assessment (score below pass mark)
"""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.assessments.models import AssessmentAttempt
from apps.notifications.models import NotificationType
from apps.notifications.services import NotificationService

logger = logging.getLogger(__name__)


@receiver(post_save, sender=AssessmentAttempt)
def suggest_remedial_path_on_failed_assessment(sender, instance: AssessmentAttempt, **kwargs):
    """
    Suggest a remedial learning path when a user fails an assessment.
    
    This signal handler:
    1. Checks if the attempt status is GRADED and is_passed is False
    2. Creates an in-app notification suggesting the user generate a remedial path
    3. Includes a link to the remedial path generation endpoint
    
    The notification provides guidance without automatically generating a path,
    allowing the user to decide whether they want remediation.
    """
    # Only process graded attempts
    if instance.status != AssessmentAttempt.AttemptStatus.GRADED:
        return
    
    # Only suggest for failed attempts
    if instance.is_passed is not False:
        return
    
    # Get the user and assessment details
    user = instance.user
    assessment = instance.assessment
    
    # Calculate percentage score for the message
    if instance.max_score and instance.max_score > 0:
        percentage = (instance.score / instance.max_score) * 100
        score_text = f"You scored {percentage:.1f}%"
    else:
        score_text = "Your score was below the passing threshold"
    
    # Build the notification message
    subject = f"Remedial Learning Path Available - {assessment.title}"
    message = (
        f"{score_text} on '{assessment.title}'. "
        f"The pass mark is {assessment.pass_mark_percentage}%.\n\n"
        f"We can create a personalized learning path to help you strengthen "
        f"the skills covered in this assessment. This path will focus on areas "
        f"where you may need additional practice.\n\n"
        f"Click 'Generate Remedial Path' in your assessment results to get started."
    )
    
    # Build the action URL for the frontend
    # This points to the assessment result page where the user can trigger path generation
    action_url = f"/assessments/{assessment.id}/attempts/{instance.id}/results"
    
    try:
        notification = NotificationService.create_notification(
            user=user,
            notification_type=NotificationType.ASSESSMENT_GRADED,
            subject=subject,
            message=message,
            action_url=action_url,
            trigger_send=True,
            preferred_methods=['IN_APP', 'EMAIL'],
        )
        
        if notification:
            logger.info(
                f"Created remedial path suggestion notification for user {user.id} "
                f"after failing assessment {assessment.id} (attempt {instance.id})"
            )
        else:
            logger.warning(
                f"Failed to create remedial path notification for user {user.id} "
                f"(assessment attempt {instance.id})"
            )
            
    except Exception as e:
        logger.error(
            f"Error creating remedial path suggestion notification for "
            f"assessment attempt {instance.id}: {e}",
            exc_info=True
        )
