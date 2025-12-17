"""
Services for the Skills app.

Provides business logic for:
- Skill gap analysis
- Learning path recommendations based on skills
- Skill proficiency updates from assessments and modules
- Skill analytics and reporting
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from django.db.models import Avg, Count, F, Q, Sum
from django.utils import timezone

from apps.courses.models import ContentItem, Module
from apps.enrollments.models import Enrollment, LearnerProgress
from apps.users.models import User

from .models import (
    AssessmentSkillMapping,
    LearnerSkillProgress,
    ModuleSkill,
    Skill,
)


@dataclass
class SkillGap:
    """Represents a skill gap for a learner."""
    skill: Skill
    current_score: int
    target_score: int
    gap: int
    priority: str  # 'high', 'medium', 'low'
    recommended_modules: list


@dataclass
class SkillRecommendation:
    """A recommendation for improving a skill."""
    skill: Skill
    module: Module
    expected_gain: int
    contribution_level: str
    reason: str


class SkillAnalysisService:
    """
    Service for analyzing learner skill gaps and providing recommendations.
    
    This service handles:
    - Identifying skill gaps for learners
    - Recommending modules to address skill gaps
    - Calculating skill proficiency from assessments
    - Generating skill analytics
    """

    def __init__(self, user: User, tenant=None):
        """
        Initialize the service.
        
        Args:
            user: The learner to analyze
            tenant: Optional tenant context (uses user's tenant if not provided)
        """
        self.user = user
        self.tenant = tenant or getattr(user, 'tenant', None)

    def get_all_skill_progress(self) -> dict[str, LearnerSkillProgress]:
        """
        Get all skill progress records for the user, keyed by skill ID.
        
        Returns:
            Dict mapping skill_id (str) to LearnerSkillProgress
        """
        progress_qs = LearnerSkillProgress.objects.filter(
            user=self.user
        ).select_related('skill')
        
        return {str(p.skill_id): p for p in progress_qs}

    def identify_skill_gaps(
        self,
        target_score: int = 50,
        include_unstarted: bool = True,
        category: Optional[str] = None,
        limit: int = 20
    ) -> list[SkillGap]:
        """
        Identify skill gaps for the learner.
        
        A skill gap is identified when:
        - The learner's proficiency is below the target score
        - The skill has relevant modules available (is teachable)
        
        Args:
            target_score: The target proficiency score (default 50 = intermediate)
            include_unstarted: Include skills with no progress record
            category: Filter by skill category
            limit: Maximum number of gaps to return
            
        Returns:
            List of SkillGap objects sorted by priority
        """
        # Get all active skills in tenant
        skills_qs = Skill.objects.filter(
            tenant=self.tenant,
            is_active=True
        )
        
        if category:
            skills_qs = skills_qs.filter(category=category)
        
        # Only include skills that have module mappings (can be learned)
        skills_with_modules = skills_qs.annotate(
            module_count=Count('module_mappings')
        ).filter(module_count__gt=0)
        
        # Get user's current progress
        user_progress = self.get_all_skill_progress()
        
        gaps = []
        for skill in skills_with_modules:
            skill_id_str = str(skill.id)
            progress = user_progress.get(skill_id_str)
            
            if progress:
                current_score = progress.proficiency_score
            elif include_unstarted:
                current_score = 0
            else:
                continue
            
            # Check if there's a gap
            if current_score < target_score:
                gap_size = target_score - current_score
                
                # Determine priority based on gap size and skill relevance
                priority = self._calculate_gap_priority(gap_size, skill)
                
                # Get recommended modules for this skill
                recommended_modules = self._get_recommended_modules_for_skill(
                    skill, current_score, limit=3
                )
                
                gaps.append(SkillGap(
                    skill=skill,
                    current_score=current_score,
                    target_score=target_score,
                    gap=gap_size,
                    priority=priority,
                    recommended_modules=recommended_modules
                ))
        
        # Sort by priority (high first) then by gap size
        priority_order = {'high': 0, 'medium': 1, 'low': 2}
        gaps.sort(key=lambda g: (priority_order.get(g.priority, 2), -g.gap))
        
        return gaps[:limit]

    def _calculate_gap_priority(self, gap_size: int, skill: Skill) -> str:
        """
        Calculate the priority of a skill gap.
        
        Priority is based on:
        - Gap size (larger = higher priority)
        - Skill category (technical skills often higher priority)
        - Number of child skills (parent skills may be higher priority)
        """
        # Large gaps are high priority
        if gap_size >= 40:
            return 'high'
        elif gap_size >= 20:
            return 'medium'
        
        # Technical skills get a slight boost
        if skill.category == Skill.Category.TECHNICAL and gap_size >= 15:
            return 'medium'
        
        return 'low'

    def _get_recommended_modules_for_skill(
        self,
        skill: Skill,
        current_score: int,
        limit: int = 5
    ) -> list[dict]:
        """
        Get recommended modules to improve a skill.
        
        Returns modules that:
        - Teach the specified skill
        - Are appropriate for the learner's current level
        - The learner hasn't completed yet
        """
        # Get completed module IDs for this user
        # A module is completed when all required content items are completed
        completed_content = LearnerProgress.objects.filter(
            enrollment__user=self.user,
            status=LearnerProgress.Status.COMPLETED
        ).values_list('content_item__module_id', flat=True)
        
        # Find modules where user completed at least one item
        # (This is a simplified check; full completion would require checking all items)
        completed_modules = set(completed_content)
        
        # Determine appropriate contribution levels based on current score
        if current_score < 25:
            preferred_levels = [
                ModuleSkill.ContributionLevel.INTRODUCES,
                ModuleSkill.ContributionLevel.DEVELOPS
            ]
        elif current_score < 50:
            preferred_levels = [
                ModuleSkill.ContributionLevel.DEVELOPS,
                ModuleSkill.ContributionLevel.REINFORCES
            ]
        else:
            preferred_levels = [
                ModuleSkill.ContributionLevel.REINFORCES,
                ModuleSkill.ContributionLevel.MASTERS
            ]
        
        # Get module-skill mappings
        mappings = ModuleSkill.objects.filter(
            skill=skill,
            module__course__tenant=self.tenant,
            module__course__is_published=True
        ).select_related('module', 'module__course').order_by(
            '-proficiency_gained', 'contribution_level'
        )
        
        recommendations = []
        for mapping in mappings:
            if mapping.module_id in completed_modules:
                continue
            
            # Calculate relevance score
            is_preferred = mapping.contribution_level in preferred_levels
            
            recommendations.append({
                'module_id': str(mapping.module_id),
                'module_title': mapping.module.title,
                'course_id': str(mapping.module.course_id),
                'course_title': mapping.module.course.title,
                'contribution_level': mapping.contribution_level,
                'proficiency_gained': mapping.proficiency_gained,
                'is_preferred_level': is_preferred
            })
            
            if len(recommendations) >= limit:
                break
        
        # Sort with preferred levels first
        recommendations.sort(key=lambda r: (not r['is_preferred_level'], -r['proficiency_gained']))
        
        return recommendations

    def get_learning_recommendations(
        self,
        max_recommendations: int = 10,
        focus_category: Optional[str] = None
    ) -> list[SkillRecommendation]:
        """
        Get personalized learning recommendations based on skill gaps.
        
        Args:
            max_recommendations: Maximum number of recommendations
            focus_category: Optional category to focus on
            
        Returns:
            List of SkillRecommendation objects
        """
        # First identify skill gaps
        gaps = self.identify_skill_gaps(
            target_score=70,  # Target advanced level for recommendations
            category=focus_category,
            limit=max_recommendations * 2
        )
        
        recommendations = []
        seen_modules = set()
        
        for gap in gaps:
            for module_info in gap.recommended_modules:
                module_id = module_info['module_id']
                
                if module_id in seen_modules:
                    continue
                
                seen_modules.add(module_id)
                
                # Determine reason for recommendation
                if gap.current_score == 0:
                    reason = f"Start learning {gap.skill.name}"
                elif gap.current_score < 30:
                    reason = f"Build foundation in {gap.skill.name}"
                elif gap.current_score < 60:
                    reason = f"Develop competency in {gap.skill.name}"
                else:
                    reason = f"Master {gap.skill.name}"
                
                recommendations.append({
                    'skill_id': str(gap.skill.id),
                    'skill_name': gap.skill.name,
                    'skill_category': gap.skill.category,
                    'module_id': module_id,
                    'module_title': module_info['module_title'],
                    'course_id': module_info['course_id'],
                    'course_title': module_info['course_title'],
                    'expected_gain': module_info['proficiency_gained'],
                    'contribution_level': module_info['contribution_level'],
                    'current_score': gap.current_score,
                    'reason': reason,
                    'priority': gap.priority
                })
                
                if len(recommendations) >= max_recommendations:
                    return recommendations
        
        return recommendations

    def update_skill_from_module_completion(
        self,
        module: Module,
        completion_quality: float = 1.0
    ) -> list[LearnerSkillProgress]:
        """
        Update learner's skill proficiency after completing a module.
        
        Args:
            module: The completed module
            completion_quality: Quality factor (0.0-1.0) based on performance
            
        Returns:
            List of updated LearnerSkillProgress records
        """
        updated_progress = []
        
        # Get all skills taught by this module
        skill_mappings = ModuleSkill.objects.filter(
            module=module
        ).select_related('skill')
        
        for mapping in skill_mappings:
            # Calculate actual proficiency gain based on quality
            base_gain = mapping.proficiency_gained
            actual_gain = int(base_gain * completion_quality)
            
            # Apply diminishing returns for reinforcement
            if mapping.contribution_level == ModuleSkill.ContributionLevel.REINFORCES:
                actual_gain = max(1, actual_gain // 2)
            
            # Get or create progress record
            progress, created = LearnerSkillProgress.objects.get_or_create(
                user=self.user,
                skill=mapping.skill
            )
            
            # Update proficiency
            progress.update_proficiency(
                score_change=actual_gain,
                source_type='module',
                source_id=str(module.id)
            )
            
            updated_progress.append(progress)
        
        return updated_progress

    def update_skill_from_assessment(
        self,
        assessment_id: str,
        question_results: list[dict]
    ) -> list[LearnerSkillProgress]:
        """
        Update learner's skill proficiency based on assessment results.
        
        Args:
            assessment_id: ID of the completed assessment
            question_results: List of {'question_id': str, 'is_correct': bool, 'score': float}
            
        Returns:
            List of updated LearnerSkillProgress records
        """
        # Build mapping of question_id to results
        results_map = {
            str(r['question_id']): r for r in question_results
        }
        
        # Get skill mappings for answered questions
        skill_mappings = AssessmentSkillMapping.objects.filter(
            question_id__in=list(results_map.keys())
        ).select_related('skill')
        
        # Aggregate results by skill
        skill_scores: dict[str, dict] = {}
        
        for mapping in skill_mappings:
            question_id = str(mapping.question_id)
            result = results_map.get(question_id, {})
            
            skill_id = str(mapping.skill_id)
            if skill_id not in skill_scores:
                skill_scores[skill_id] = {
                    'skill': mapping.skill,
                    'total_weight': 0,
                    'earned_weight': 0,
                    'question_count': 0,
                    'correct_count': 0
                }
            
            skill_scores[skill_id]['total_weight'] += mapping.weight
            skill_scores[skill_id]['question_count'] += 1
            
            if result.get('is_correct'):
                skill_scores[skill_id]['earned_weight'] += mapping.weight
                skill_scores[skill_id]['correct_count'] += 1
        
        # Update skill progress
        updated_progress = []
        
        for skill_id, scores in skill_scores.items():
            skill = scores['skill']
            
            # Calculate proficiency change based on weighted score
            if scores['total_weight'] > 0:
                accuracy = scores['earned_weight'] / scores['total_weight']
            else:
                accuracy = 0
            
            # Determine proficiency change
            # Good performance increases proficiency, poor performance may decrease it
            if accuracy >= 0.8:
                # Excellent performance
                score_change = min(15, scores['correct_count'] * 3)
            elif accuracy >= 0.6:
                # Good performance
                score_change = min(10, scores['correct_count'] * 2)
            elif accuracy >= 0.4:
                # Mediocre performance - small gain
                score_change = max(1, scores['correct_count'])
            else:
                # Poor performance - no change or slight decrease
                score_change = 0
            
            if score_change > 0:
                # Get or create progress record
                progress, created = LearnerSkillProgress.objects.get_or_create(
                    user=self.user,
                    skill=skill
                )
                
                progress.update_proficiency(
                    score_change=score_change,
                    source_type='assessment',
                    source_id=assessment_id
                )
                
                updated_progress.append(progress)
        
        return updated_progress

    def get_skill_analytics(self, skill_id: Optional[str] = None) -> dict:
        """
        Get skill analytics for the learner.
        
        Args:
            skill_id: Optional specific skill to analyze
            
        Returns:
            Dict containing analytics data
        """
        progress_qs = LearnerSkillProgress.objects.filter(user=self.user)
        
        if skill_id:
            progress_qs = progress_qs.filter(skill_id=skill_id)
        
        progress_qs = progress_qs.select_related('skill')
        
        # Overall stats
        stats = progress_qs.aggregate(
            total_skills=Count('id'),
            avg_proficiency=Avg('proficiency_score'),
            skills_mastered=Count('id', filter=Q(proficiency_score__gte=90)),
            skills_advanced=Count('id', filter=Q(proficiency_score__gte=70, proficiency_score__lt=90)),
            skills_intermediate=Count('id', filter=Q(proficiency_score__gte=50, proficiency_score__lt=70)),
            skills_beginner=Count('id', filter=Q(proficiency_score__gte=25, proficiency_score__lt=50)),
            skills_novice=Count('id', filter=Q(proficiency_score__lt=25))
        )
        
        # Category breakdown
        category_stats = progress_qs.values('skill__category').annotate(
            count=Count('id'),
            avg_score=Avg('proficiency_score')
        ).order_by('-avg_score')
        
        # Recent activity
        recent_cutoff = timezone.now() - timedelta(days=30)
        active_skills = []
        
        for progress in progress_qs:
            trend = progress.get_progress_trend(days=30)
            if trend['num_activities'] > 0:
                active_skills.append({
                    'skill_id': str(progress.skill_id),
                    'skill_name': progress.skill.name,
                    'current_score': progress.proficiency_score,
                    'trend': trend['direction'],
                    'change': trend['total_change']
                })
        
        return {
            'total_skills_tracked': stats['total_skills'] or 0,
            'average_proficiency': round(stats['avg_proficiency'] or 0, 1),
            'skills_by_level': {
                'mastered': stats['skills_mastered'] or 0,
                'advanced': stats['skills_advanced'] or 0,
                'intermediate': stats['skills_intermediate'] or 0,
                'beginner': stats['skills_beginner'] or 0,
                'novice': stats['skills_novice'] or 0
            },
            'category_breakdown': [
                {
                    'category': cat['skill__category'],
                    'count': cat['count'],
                    'average_score': round(cat['avg_score'], 1)
                }
                for cat in category_stats
            ],
            'active_skills': active_skills[:10]
        }


class SkillCoverageService:
    """
    Service for analyzing skill coverage across courses and assessments.
    
    Used by instructors/admins to ensure courses adequately cover required skills.
    """

    def __init__(self, tenant):
        """
        Initialize the service.
        
        Args:
            tenant: The tenant context
        """
        self.tenant = tenant

    def get_course_skill_coverage(self, course_id: str) -> dict:
        """
        Analyze skill coverage for a course.
        
        Returns breakdown of which skills are covered by the course's modules.
        """
        from apps.courses.models import Course
        
        course = Course.objects.get(id=course_id, tenant=self.tenant)
        
        # Get all module-skill mappings for this course
        mappings = ModuleSkill.objects.filter(
            module__course=course
        ).select_related('skill', 'module')
        
        # Aggregate by skill
        skills_covered = {}
        for mapping in mappings:
            skill_id = str(mapping.skill_id)
            if skill_id not in skills_covered:
                skills_covered[skill_id] = {
                    'skill_id': skill_id,
                    'skill_name': mapping.skill.name,
                    'skill_category': mapping.skill.category,
                    'modules': [],
                    'total_proficiency_possible': 0,
                    'contribution_levels': set()
                }
            
            skills_covered[skill_id]['modules'].append({
                'module_id': str(mapping.module_id),
                'module_title': mapping.module.title,
                'contribution_level': mapping.contribution_level,
                'proficiency_gained': mapping.proficiency_gained
            })
            skills_covered[skill_id]['total_proficiency_possible'] += mapping.proficiency_gained
            skills_covered[skill_id]['contribution_levels'].add(mapping.contribution_level)
        
        # Convert sets to lists
        for skill in skills_covered.values():
            skill['contribution_levels'] = list(skill['contribution_levels'])
        
        return {
            'course_id': str(course.id),
            'course_title': course.title,
            'total_skills_covered': len(skills_covered),
            'skills': list(skills_covered.values())
        }

    def identify_coverage_gaps(self, course_id: str) -> dict:
        """
        Identify skills that are not adequately covered by a course.
        
        A skill is considered inadequately covered if:
        - It's a core skill in the category but has no modules
        - It's introduced but never developed or reinforced
        """
        coverage = self.get_course_skill_coverage(course_id)
        covered_skill_ids = {s['skill_id'] for s in coverage['skills']}
        
        # Get all active skills in tenant
        all_skills = Skill.objects.filter(
            tenant=self.tenant,
            is_active=True
        )
        
        # Find skills not covered at all
        uncovered = []
        for skill in all_skills:
            if str(skill.id) not in covered_skill_ids:
                # Check if this skill is related to course topics (basic heuristic)
                uncovered.append({
                    'skill_id': str(skill.id),
                    'skill_name': skill.name,
                    'skill_category': skill.category,
                    'reason': 'not_covered'
                })
        
        # Find skills that are only introduced (not developed)
        incomplete = []
        for skill_data in coverage['skills']:
            levels = skill_data['contribution_levels']
            if levels == [ModuleSkill.ContributionLevel.INTRODUCES]:
                incomplete.append({
                    'skill_id': skill_data['skill_id'],
                    'skill_name': skill_data['skill_name'],
                    'skill_category': skill_data['skill_category'],
                    'current_coverage': levels,
                    'reason': 'only_introduced',
                    'suggestion': 'Add modules that develop or reinforce this skill'
                })
        
        return {
            'course_id': course_id,
            'uncovered_skills': uncovered,
            'incomplete_coverage': incomplete,
            'total_gaps': len(uncovered) + len(incomplete)
        }

    def get_assessment_skill_coverage(self, assessment_id: str) -> dict:
        """
        Analyze skill coverage for an assessment.
        
        Returns breakdown of which skills are evaluated by the assessment.
        """
        from apps.assessments.models import Assessment
        
        assessment = Assessment.objects.get(id=assessment_id)
        
        # Get all assessment-skill mappings
        mappings = AssessmentSkillMapping.objects.filter(
            question__assessment=assessment
        ).select_related('skill', 'question')
        
        # Aggregate by skill
        skills_evaluated = {}
        for mapping in mappings:
            skill_id = str(mapping.skill_id)
            if skill_id not in skills_evaluated:
                skills_evaluated[skill_id] = {
                    'skill_id': skill_id,
                    'skill_name': mapping.skill.name,
                    'skill_category': mapping.skill.category,
                    'questions': [],
                    'total_weight': 0,
                    'proficiency_levels': set()
                }
            
            skills_evaluated[skill_id]['questions'].append({
                'question_id': str(mapping.question_id),
                'question_order': mapping.question.order,
                'weight': mapping.weight,
                'proficiency_required': mapping.proficiency_required
            })
            skills_evaluated[skill_id]['total_weight'] += mapping.weight
            skills_evaluated[skill_id]['proficiency_levels'].add(mapping.proficiency_required)
        
        # Convert sets to lists
        for skill in skills_evaluated.values():
            skill['proficiency_levels'] = list(skill['proficiency_levels'])
        
        return {
            'assessment_id': str(assessment.id),
            'assessment_title': assessment.title,
            'total_skills_evaluated': len(skills_evaluated),
            'skills': list(skills_evaluated.values())
        }
