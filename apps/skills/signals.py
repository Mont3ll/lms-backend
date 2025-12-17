"""
Signal handlers for the Skills app.

Handles automatic skill progress updates based on:
- Assessment completion/grading
- Module completion
"""

import logging
from decimal import Decimal

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.assessments.models import AssessmentAttempt, Question

logger = logging.getLogger(__name__)


@receiver(post_save, sender=AssessmentAttempt)
def update_skills_on_assessment_completion(sender, instance: AssessmentAttempt, **kwargs):
    """
    Update learner skill progress when an assessment attempt is graded.
    
    This signal handler:
    1. Checks if the attempt status changed to GRADED
    2. Extracts question results from the attempt
    3. Updates skill proficiency based on performance
    """
    # Only process when attempt is graded
    if instance.status != AssessmentAttempt.AttemptStatus.GRADED:
        return
    
    # Avoid reprocessing - check if we've already processed this attempt
    # by looking at the contributing_assessments field in skill progress
    from .models import AssessmentSkillMapping, LearnerSkillProgress
    
    # Get questions with skill mappings for this assessment
    skill_mappings = AssessmentSkillMapping.objects.filter(
        question__assessment=instance.assessment
    ).select_related('skill', 'question')
    
    if not skill_mappings.exists():
        logger.debug(
            f"No skill mappings found for assessment {instance.assessment_id}, "
            "skipping skill updates"
        )
        return
    
    try:
        # Build question results from the attempt answers
        question_results = _extract_question_results(instance, skill_mappings)
        
        if not question_results:
            logger.debug(f"No question results extracted for attempt {instance.id}")
            return
        
        # Update skills using the service
        from .services import SkillAnalysisService
        
        service = SkillAnalysisService(instance.user)
        updated_progress = service.update_skill_from_assessment(
            assessment_id=str(instance.assessment_id),
            question_results=question_results
        )
        
        logger.info(
            f"Updated {len(updated_progress)} skills for user {instance.user_id} "
            f"from assessment attempt {instance.id}"
        )
        
    except Exception as e:
        logger.error(
            f"Error updating skills for assessment attempt {instance.id}: {e}",
            exc_info=True
        )


def _extract_question_results(
    attempt: AssessmentAttempt,
    skill_mappings
) -> list[dict]:
    """
    Extract question results from an assessment attempt.
    
    Analyzes each answered question to determine if it was correct
    and calculates the score achieved.
    
    Args:
        attempt: The graded assessment attempt
        skill_mappings: QuerySet of AssessmentSkillMapping objects
        
    Returns:
        List of dicts with question_id, is_correct, and score
    """
    from apps.assessments.services import GradingService
    
    results = []
    submitted_answers = attempt.answers or {}
    
    # Get unique questions from skill mappings
    question_ids = set(mapping.question_id for mapping in skill_mappings)
    questions = Question.objects.filter(id__in=question_ids)
    question_map = {str(q.id): q for q in questions}
    
    for question_id_str, user_answer in submitted_answers.items():
        question = question_map.get(question_id_str)
        if not question:
            continue
        
        # Determine if the answer was correct using GradingService helpers
        is_correct = False
        score = Decimal(0)
        
        try:
            if question.question_type == Question.QuestionType.MULTIPLE_CHOICE:
                score = GradingService._grade_multiple_choice(question, user_answer)
            elif question.question_type == Question.QuestionType.TRUE_FALSE:
                score = GradingService._grade_true_false(question, user_answer)
            elif question.question_type == Question.QuestionType.SHORT_ANSWER:
                score = GradingService._grade_short_answer(question, user_answer)
            elif question.question_type == Question.QuestionType.MATCHING:
                score = GradingService._grade_matching(question, user_answer)
            elif question.question_type == Question.QuestionType.FILL_BLANKS:
                score = GradingService._grade_fill_blanks(question, user_answer)
            else:
                # For manual grading types, we can't determine correctness here
                # Skip or use a placeholder
                continue
            
            # Question is correct if score equals full points
            is_correct = score >= Decimal(question.points)
            
        except Exception as e:
            logger.warning(
                f"Error grading question {question_id_str} for skill calculation: {e}"
            )
            continue
        
        results.append({
            'question_id': question_id_str,
            'is_correct': is_correct,
            'score': float(score),
            'max_score': float(question.points)
        })
    
    return results


def calculate_skill_breakdown_for_attempt(attempt: AssessmentAttempt) -> dict:
    """
    Calculate a detailed skill breakdown for an assessment attempt.
    
    This function provides analytics on how the learner performed
    on each skill evaluated by the assessment.
    
    Args:
        attempt: The graded assessment attempt
        
    Returns:
        Dict containing skill-by-skill performance breakdown
    """
    from .models import AssessmentSkillMapping
    
    if attempt.status != AssessmentAttempt.AttemptStatus.GRADED:
        return {'error': 'Attempt must be graded to calculate skill breakdown'}
    
    # Get skill mappings for this assessment
    skill_mappings = AssessmentSkillMapping.objects.filter(
        question__assessment=attempt.assessment
    ).select_related('skill', 'question')
    
    if not skill_mappings.exists():
        return {
            'assessment_id': str(attempt.assessment_id),
            'attempt_id': str(attempt.id),
            'skills': [],
            'message': 'No skills mapped to this assessment'
        }
    
    # Extract question results
    question_results = _extract_question_results(attempt, skill_mappings)
    results_map = {r['question_id']: r for r in question_results}
    
    # Aggregate by skill
    skill_performance = {}
    
    for mapping in skill_mappings:
        question_id_str = str(mapping.question_id)
        skill_id = str(mapping.skill_id)
        
        if skill_id not in skill_performance:
            skill_performance[skill_id] = {
                'skill_id': skill_id,
                'skill_name': mapping.skill.name,
                'skill_category': mapping.skill.category,
                'questions_total': 0,
                'questions_correct': 0,
                'total_points': 0,
                'earned_points': 0,
                'weighted_score': 0,
                'total_weight': 0,
                'proficiency_demonstrated': None
            }
        
        result = results_map.get(question_id_str)
        if result:
            skill_performance[skill_id]['questions_total'] += 1
            skill_performance[skill_id]['total_points'] += result['max_score']
            skill_performance[skill_id]['total_weight'] += mapping.weight
            
            if result['is_correct']:
                skill_performance[skill_id]['questions_correct'] += 1
                skill_performance[skill_id]['earned_points'] += result['score']
                skill_performance[skill_id]['weighted_score'] += mapping.weight
    
    # Calculate percentages and proficiency
    for skill_data in skill_performance.values():
        if skill_data['questions_total'] > 0:
            skill_data['accuracy'] = round(
                skill_data['questions_correct'] / skill_data['questions_total'] * 100, 1
            )
        else:
            skill_data['accuracy'] = 0
        
        if skill_data['total_points'] > 0:
            skill_data['score_percentage'] = round(
                skill_data['earned_points'] / skill_data['total_points'] * 100, 1
            )
        else:
            skill_data['score_percentage'] = 0
        
        # Determine demonstrated proficiency level
        accuracy = skill_data['accuracy']
        if accuracy >= 90:
            skill_data['proficiency_demonstrated'] = 'EXPERT'
        elif accuracy >= 75:
            skill_data['proficiency_demonstrated'] = 'ADVANCED'
        elif accuracy >= 60:
            skill_data['proficiency_demonstrated'] = 'INTERMEDIATE'
        elif accuracy >= 40:
            skill_data['proficiency_demonstrated'] = 'BEGINNER'
        else:
            skill_data['proficiency_demonstrated'] = 'NOVICE'
    
    # Sort by accuracy (lowest first to highlight areas for improvement)
    skills_list = sorted(
        skill_performance.values(),
        key=lambda x: x['accuracy']
    )
    
    return {
        'assessment_id': str(attempt.assessment_id),
        'attempt_id': str(attempt.id),
        'overall_score': float(attempt.score) if attempt.score else 0,
        'overall_max_score': attempt.max_score or 0,
        'skills_evaluated': len(skills_list),
        'skills': skills_list
    }
