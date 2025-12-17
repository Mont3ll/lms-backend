import importlib
import logging
import uuid

import requests
from django.conf import settings
from django.utils import timezone

from .models import (
    GeneratedContent,
    GenerationJob,
    ModelConfig,
    PromptTemplate,
    Tenant,
    User,
)
from .tasks import trigger_ai_generation_task  # Celery task

logger = logging.getLogger(__name__)


class AIAdapterError(Exception):
    pass


class AIAdapterFactory:
    """Factory to get the correct adapter based on provider type."""

    _adapter_cache = {}

    @classmethod
    def get_adapter(cls, provider_name: str):
        if provider_name in cls._adapter_cache:
            return cls._adapter_cache[provider_name]

        adapter_module_path = f"apps.ai_engine.adapters.{provider_name.lower()}_adapter"
        adapter_class_name = f"{provider_name.capitalize()}Adapter"

        try:
            module = importlib.import_module(adapter_module_path)
            adapter_class = getattr(module, adapter_class_name)
            cls._adapter_cache[provider_name] = adapter_class
            return adapter_class
        except (ImportError, AttributeError) as e:
            logger.error(
                f"Could not load AI adapter for provider '{provider_name}': {e}"
            )
            raise AIAdapterError(
                f"Adapter for provider '{provider_name}' not found or invalid."
            ) from e


class ContentGeneratorService:
    """Service for managing AI content generation jobs."""

    @staticmethod
    def start_generation_job(
        *,
        tenant: Tenant,
        user: User,
        prompt_template: PromptTemplate | None = None,
        model_config: ModelConfig | None = None,
        input_context: dict,
        generation_params: dict | None = None,
        custom_prompt: str | None = None,  # Allow direct prompt? Needs careful handling
    ) -> GenerationJob:
        """Creates a GenerationJob record and triggers the async Celery task."""

        if not tenant or not user:
            raise ValueError("Tenant and User are required.")
        if not prompt_template and not custom_prompt:
            raise ValueError(
                "Either prompt_template or custom_prompt must be provided."
            )
        if prompt_template and custom_prompt:
            raise ValueError(
                "Provide either prompt_template or custom_prompt, not both."
            )

        final_model_config = model_config or (
            prompt_template.default_model_config if prompt_template else None
        )
        if not final_model_config:
            raise ValueError(
                "AI Model Configuration must be specified directly or via prompt template default."
            )
        if not final_model_config.is_active:
            raise ValueError(
                f"Model Configuration '{final_model_config.name}' is not active."
            )

        # Prepare the prompt
        if prompt_template:
            try:
                final_prompt = prompt_template.template_text.format(**input_context)
            except KeyError as e:
                raise ValueError(
                    f"Missing variable '{e}' in input_context for template '{prompt_template.name}'."
                )
        else:
            # Security risk: Ensure custom prompts are handled safely (e.g., no injection)
            final_prompt = custom_prompt or ""  # Should have been validated earlier

        # Merge generation parameters
        final_params = final_model_config.default_params.copy()
        if generation_params:
            final_params.update(generation_params)

        # Create the job record
        job = GenerationJob.objects.create(
            tenant=tenant,
            user=user,
            prompt_template=prompt_template,
            model_config_used=final_model_config,
            status=GenerationJob.JobStatus.PENDING,
            input_prompt=final_prompt,  # Store the rendered prompt
            input_context=input_context,
            generation_params=final_params,
        )
        logger.info(f"Created AI Generation Job {job.id} by user {user.id}")

        # Trigger Celery task
        task = trigger_ai_generation_task.delay(job.id)
        job.celery_task_id = task.id
        job.save(update_fields=["celery_task_id"])
        logger.info(f"Dispatched Celery task {task.id} for job {job.id}")

        return job

    @staticmethod
    def execute_generation(job_id: uuid.UUID):
        """
        Executes the actual AI generation call. Called by the Celery task.
        """
        try:
            job = GenerationJob.objects.select_related(
                "model_config_used", "tenant", "user"
            ).get(pk=job_id)
        except GenerationJob.DoesNotExist:
            logger.error(f"Generation Job {job_id} not found for execution.")
            return

        if job.status != GenerationJob.JobStatus.PENDING:
            logger.warning(
                f"Generation Job {job_id} is not in PENDING state (status: {job.status}). Skipping execution."
            )
            return

        job.status = GenerationJob.JobStatus.IN_PROGRESS
        job.started_at = timezone.now()
        job.save(update_fields=["status", "started_at"])
        logger.info(f"Executing AI Generation Job {job.id}...")

        model_config = job.model_config_used
        if not model_config:
            job.status = GenerationJob.JobStatus.FAILED
            job.error_message = "Model configuration missing for job execution."
            job.completed_at = timezone.now()
            job.save(update_fields=["status", "error_message", "completed_at"])
            logger.error(job.error_message)
            return

        try:
            # Get the appropriate adapter
            AdapterClass = AIAdapterFactory.get_adapter(model_config.provider)
            adapter_instance = AdapterClass(config=model_config)

            # Make the API call
            generated_text, metadata = adapter_instance.generate(
                prompt=job.input_prompt, params=job.generation_params
            )

            # Save the result
            GeneratedContent.objects.create(
                job=job,
                tenant=job.tenant,
                user=job.user,  # User who initiated
                generated_text=generated_text,
                metadata=metadata,
            )

            # Mark job as completed
            job.status = GenerationJob.JobStatus.COMPLETED
            job.completed_at = timezone.now()
            job.save(update_fields=["status", "completed_at"])
            logger.info(f"Successfully completed AI Generation Job {job.id}")

        except Exception as e:
            logger.error(
                f"Error executing AI Generation Job {job.id}: {e}", exc_info=True
            )
            job.status = GenerationJob.JobStatus.FAILED
            job.error_message = f"Generation failed: {e}"
            job.completed_at = timezone.now()
            job.save(update_fields=["status", "error_message", "completed_at"])


class PersonalizationService:
    """Service for content personalization using AI/ML."""

    @staticmethod
    def recommend_content(user: User, context: dict = None) -> list:
        """
        Recommend courses and content items for a user based on their activity,
        enrollments, and interests.
        
        Uses ML-based hybrid recommendations (collaborative + content-based filtering)
        as the primary approach, with a fallback to rule-based recommendations.
        
        Args:
            user: The user to generate recommendations for
            context: Optional context dict with keys like:
                - 'limit': Number of recommendations (default 10)
                - 'exclude_enrolled': Whether to exclude enrolled courses (default True)
                - 'use_ml': Whether to use ML recommendations (default True)
                - 'include_learning_paths': Whether to include learning paths (default True)
                - 'tenant_id': Optional tenant ID for filtering
        
        Returns:
            List of recommended content items (courses, learning paths, etc.)
        """
        context = context or {}
        limit = context.get('limit', 10)
        exclude_enrolled = context.get('exclude_enrolled', True)
        use_ml = context.get('use_ml', True)
        include_learning_paths = context.get('include_learning_paths', True)
        tenant_id = context.get('tenant_id')
        
        recommendations = []
        
        try:
            # Try ML-based recommendations first
            if use_ml:
                ml_recommendations = PersonalizationService._get_ml_recommendations(
                    user=user,
                    limit=limit,
                    exclude_enrolled=exclude_enrolled,
                    tenant_id=tenant_id
                )
                
                if ml_recommendations:
                    recommendations.extend(ml_recommendations)
                    logger.info(
                        f"Generated {len(ml_recommendations)} ML-based recommendations for user {user.id}"
                    )
            
            # If ML didn't provide enough recommendations, supplement with rule-based
            if len(recommendations) < limit:
                remaining = limit - len(recommendations)
                existing_ids = {r['id'] for r in recommendations}
                
                rule_based = PersonalizationService._get_rule_based_recommendations(
                    user=user,
                    limit=remaining,
                    exclude_enrolled=exclude_enrolled,
                    exclude_ids=existing_ids
                )
                
                recommendations.extend(rule_based)
            
            # Add learning path recommendations if requested
            if include_learning_paths:
                path_recs = PersonalizationService._get_learning_path_recommendations(
                    user=user, 
                    limit=3
                )
                recommendations.extend(path_recs)
            
            # Sort by score
            recommendations.sort(key=lambda x: x.get('score', 0), reverse=True)
            
            logger.info(f"Generated {len(recommendations)} total recommendations for user {user.id}")
            return recommendations[:limit]
            
        except Exception as e:
            logger.error(f"Error generating recommendations for user {user.id}: {e}", exc_info=True)
            return []

    @staticmethod
    def _get_ml_recommendations(
        user: User,
        limit: int,
        exclude_enrolled: bool,
        tenant_id: str = None
    ) -> list:
        """
        Get recommendations using the ML hybrid recommender.
        
        Args:
            user: The user to generate recommendations for
            limit: Number of recommendations to return
            exclude_enrolled: Whether to exclude enrolled courses
            tenant_id: Optional tenant ID for filtering
            
        Returns:
            List of recommendation dictionaries
        """
        from .recommenders import get_hybrid_recommender
        
        try:
            recommender = get_hybrid_recommender()
            
            # Fit the model if needed (lazy initialization)
            if recommender.is_model_stale(max_age_hours=24):
                logger.info("ML recommender model is stale, refitting...")
                recommender.fit(tenant_id=tenant_id)
            
            # If model still not fitted (insufficient data), return empty
            if not recommender._model_fitted:
                logger.debug("ML recommender model not fitted, falling back to rule-based")
                return []
            
            # Get ML recommendations
            ml_results = recommender.recommend(
                user_id=str(user.id),
                n_recommendations=limit,
                exclude_enrolled=exclude_enrolled
            )
            
            # Convert RecommendationResult objects to dicts
            recommendations = []
            for result in ml_results:
                rec_dict = result.to_dict()
                # Normalize the format to match the service's expected output
                recommendations.append({
                    'type': rec_dict.get('type', 'course'),
                    'id': rec_dict['id'],
                    'title': rec_dict['title'],
                    'slug': rec_dict.get('slug', ''),
                    'description': rec_dict.get('description', ''),
                    'category': rec_dict.get('category', ''),
                    'difficulty_level': rec_dict.get('difficulty_level', ''),
                    'reason': rec_dict['reason'],
                    'score': rec_dict['score'],
                    'algorithm': rec_dict.get('algorithm', 'hybrid'),
                    'sources': rec_dict.get('sources', [])
                })
            
            return recommendations
            
        except ImportError as e:
            logger.warning(f"ML recommender not available (missing dependencies): {e}")
            return []
        except Exception as e:
            logger.error(f"Error getting ML recommendations: {e}", exc_info=True)
            return []

    @staticmethod
    def _get_rule_based_recommendations(
        user: User,
        limit: int,
        exclude_enrolled: bool,
        exclude_ids: set = None
    ) -> list:
        """
        Get rule-based recommendations using category/tag matching and popularity.
        
        This is the fallback when ML recommendations are unavailable or insufficient.
        
        Args:
            user: The user to generate recommendations for
            limit: Number of recommendations to return
            exclude_enrolled: Whether to exclude enrolled courses
            exclude_ids: Set of course IDs to exclude (already recommended)
            
        Returns:
            List of recommendation dictionaries
        """
        from apps.courses.models import Course
        from apps.enrollments.models import Enrollment
        from django.db.models import Count, Avg
        
        exclude_ids = exclude_ids or set()
        recommendations = []
        
        try:
            # Get user's enrolled courses to understand their interests
            user_enrollments = Enrollment.objects.filter(user=user).select_related('course')
            enrolled_course_ids = list(user_enrollments.values_list('course_id', flat=True))
            
            # Extract categories/tags from enrolled courses
            enrolled_courses = Course.objects.filter(id__in=enrolled_course_ids)
            user_categories = set()
            user_tags = set()
            
            for course in enrolled_courses:
                if course.category:
                    user_categories.add(course.category)
                if hasattr(course, 'tags') and course.tags:
                    user_tags.update(course.tags if isinstance(course.tags, list) else [])
            
            # Build recommendation query
            base_query = Course.objects.filter(status=Course.Status.PUBLISHED)
            
            if exclude_enrolled and enrolled_course_ids:
                base_query = base_query.exclude(id__in=enrolled_course_ids)
            
            # Exclude already recommended courses
            if exclude_ids:
                base_query = base_query.exclude(id__in=exclude_ids)
            
            # Score courses based on relevance
            recommended_courses = base_query.annotate(
                enrollment_count=Count('enrollments'),
                avg_rating=Avg('enrollments__progress')
            )
            
            # Prioritize courses in user's preferred categories
            if user_categories:
                category_courses = recommended_courses.filter(
                    category__in=user_categories
                ).order_by('-enrollment_count')[:limit // 2]
                
                for course in category_courses:
                    recommendations.append({
                        'type': 'course',
                        'id': str(course.id),
                        'title': course.title,
                        'slug': course.slug,
                        'description': course.description[:200] if course.description else '',
                        'category': course.category,
                        'enrollment_count': course.enrollment_count,
                        'reason': 'Based on your interests',
                        'score': 0.75,
                        'algorithm': 'rule_based'
                    })
            
            # Add popular courses the user hasn't enrolled in
            remaining_slots = limit - len(recommendations)
            if remaining_slots > 0:
                popular_courses = recommended_courses.exclude(
                    id__in=[r['id'] for r in recommendations if r['type'] == 'course']
                ).order_by('-enrollment_count')[:remaining_slots]
                
                for course in popular_courses:
                    recommendations.append({
                        'type': 'course',
                        'id': str(course.id),
                        'title': course.title,
                        'slug': course.slug,
                        'description': course.description[:200] if course.description else '',
                        'category': course.category,
                        'enrollment_count': course.enrollment_count,
                        'reason': 'Popular with other learners',
                        'score': 0.6,
                        'algorithm': 'popularity'
                    })
            
            return recommendations
            
        except Exception as e:
            logger.error(f"Error getting rule-based recommendations: {e}", exc_info=True)
            return []

    @staticmethod
    def _get_learning_path_recommendations(user: User, limit: int = 3) -> list:
        """
        Get learning path recommendations.
        
        Args:
            user: The user to generate recommendations for
            limit: Number of learning paths to return
            
        Returns:
            List of learning path recommendation dictionaries
        """
        from apps.learning_paths.models import LearningPath
        from django.db.models import Count
        
        recommendations = []
        
        try:
            learning_paths = LearningPath.objects.filter(
                is_published=True
            ).annotate(
                progress_count=Count('progress_records')
            ).order_by('-progress_count')[:limit]
            
            for path in learning_paths:
                recommendations.append({
                    'type': 'learning_path',
                    'id': str(path.id),
                    'title': path.title,
                    'slug': path.slug,
                    'description': path.description[:200] if path.description else '',
                    'reason': 'Recommended learning path',
                    'score': 0.8,
                    'algorithm': 'popularity'
                })
        except Exception as e:
            logger.debug(f"Could not fetch learning paths for recommendations: {e}")
        
        return recommendations

    @staticmethod
    def get_similar_courses(course_id: str, limit: int = 5) -> list:
        """
        Get courses similar to a given course using content-based filtering.
        
        Args:
            course_id: The course ID to find similar courses for
            limit: Number of similar courses to return
            
        Returns:
            List of similar course dictionaries
        """
        from .recommenders import get_content_based_recommender
        
        try:
            recommender = get_content_based_recommender()
            
            # Fit if needed
            if recommender.is_model_stale(max_age_hours=24):
                recommender.fit()
            
            if not recommender._model_fitted:
                return []
            
            results = recommender.get_similar_courses(course_id, limit)
            
            return [result.to_dict() for result in results]
            
        except ImportError:
            logger.warning("Content-based recommender not available")
            return []
        except Exception as e:
            logger.error(f"Error getting similar courses: {e}", exc_info=True)
            return []

    @staticmethod
    def recommend_modules(user: User, context: dict = None) -> list:
        """
        Recommend modules for a user based on skill gaps, prerequisites, and
        collaborative filtering.
        
        Uses the ModuleRecommender to generate personalized module recommendations
        that consider:
        - User's current skill proficiencies and gaps
        - Module prerequisites (ensuring user is ready for the content)
        - What similar learners have completed successfully
        - Target skills the user wants to develop
        
        Args:
            user: The user to generate recommendations for
            context: Optional context dict with keys:
                - 'limit': Number of recommendations (default 10)
                - 'course_id': Filter to a specific course
                - 'target_skills': List of skill IDs to focus on
                - 'exclude_completed': Whether to exclude completed modules (default True)
                - 'check_prerequisites': Whether to filter by prerequisites (default True)
                - 'skill_weight': Weight for skill-based scoring (default 0.5)
                - 'collaborative_weight': Weight for collaborative filtering (default 0.3)
                - 'popularity_weight': Weight for popularity scoring (default 0.2)
        
        Returns:
            List of recommended modules with scores and reasons
        """
        from .recommenders import ModuleRecommender
        
        context = context or {}
        limit = context.get('limit', 10)
        course_id = context.get('course_id')
        target_skills = context.get('target_skills', [])
        exclude_completed = context.get('exclude_completed', True)
        check_prerequisites = context.get('check_prerequisites', True)
        skill_weight = context.get('skill_weight', 0.5)
        collaborative_weight = context.get('collaborative_weight', 0.3)
        popularity_weight = context.get('popularity_weight', 0.2)
        
        try:
            # Create recommender instance
            recommender = ModuleRecommender(
                user=user,
                target_skills=target_skills,
                skill_weight=skill_weight,
                collaborative_weight=collaborative_weight,
                popularity_weight=popularity_weight
            )
            
            # Get recommendations
            results = recommender.get_recommendations(
                limit=limit,
                course_id=course_id,
                exclude_completed=exclude_completed,
                check_prerequisites=check_prerequisites
            )
            
            # Convert to dictionaries
            recommendations = []
            for result in results:
                rec_dict = result.to_dict()
                recommendations.append({
                    'type': 'module',
                    'id': rec_dict['id'],
                    'title': rec_dict['title'],
                    'score': rec_dict['score'],
                    'reason': rec_dict['reason'],
                    'course_id': rec_dict.get('metadata', {}).get('course_id', ''),
                    'course_title': rec_dict.get('metadata', {}).get('course_title', ''),
                    'course_slug': rec_dict.get('metadata', {}).get('course_slug', ''),
                    'module_order': rec_dict.get('metadata', {}).get('module_order', 0),
                    'description': rec_dict.get('metadata', {}).get('description', ''),
                    'skills': rec_dict.get('metadata', {}).get('skills', []),
                    'algorithm': rec_dict.get('metadata', {}).get('algorithm', 'module_recommender')
                })
            
            logger.info(f"Generated {len(recommendations)} module recommendations for user {user.id}")
            return recommendations
            
        except Exception as e:
            logger.error(f"Error generating module recommendations for user {user.id}: {e}", exc_info=True)
            return []

    @staticmethod
    def get_module_sequence(
        user: User,
        course_id: str = None,
        target_skills: list[str] = None,
        max_modules: int = 10
    ) -> dict:
        """
        Generate an optimal learning sequence of modules for a user.
        
        Creates a structured learning path that respects prerequisites and
        optimizes for skill development progression. The sequence considers:
        - Module prerequisites (topological ordering)
        - Skill gap priorities (addressing biggest gaps first)
        - Progressive difficulty (building up to advanced content)
        
        Args:
            user: The user to generate the sequence for
            course_id: Optional course ID to limit modules to
            target_skills: Optional list of skill IDs to optimize for
            max_modules: Maximum number of modules in the sequence (default 10)
        
        Returns:
            Dict with:
                - 'sequence': Ordered list of modules to complete
                - 'total_modules': Total count of modules in sequence
                - 'estimated_skill_gains': Projected skill improvements
                - 'skill_gap_analysis': Current skill gaps being addressed
        """
        from .recommenders import ModuleRecommender
        from apps.courses.models import Module, ModulePrerequisite
        from apps.skills.models import ModuleSkill, LearnerSkillProgress
        from collections import defaultdict
        
        try:
            # Get skill gap analysis first
            recommender = ModuleRecommender(
                user=user,
                target_skills=target_skills or []
            )
            
            skill_gaps = recommender.get_skill_gap_analysis(target_skills)
            
            # Get module recommendations (more than needed for ordering)
            recommendations = recommender.get_recommendations(
                limit=max_modules * 2,
                course_id=course_id,
                exclude_completed=True,
                check_prerequisites=True
            )
            
            if not recommendations:
                return {
                    'sequence': [],
                    'total_modules': 0,
                    'estimated_skill_gains': {},
                    'skill_gap_analysis': skill_gaps,
                    'message': 'No eligible modules found'
                }
            
            # Build prerequisite graph for ordering
            module_ids = [r.item_id for r in recommendations]
            modules = {
                str(m.id): m
                for m in Module.objects.filter(
                    id__in=module_ids
                ).prefetch_related('prerequisites', 'skill_mappings__skill')
            }
            
            # Build adjacency list for prerequisites
            prereq_graph = defaultdict(list)
            in_degree = defaultdict(int)
            
            for mod_id, module in modules.items():
                if mod_id not in in_degree:
                    in_degree[mod_id] = 0
                    
                for prereq in ModulePrerequisite.objects.filter(module_id=mod_id):
                    prereq_mod_id = str(prereq.prerequisite_module_id)
                    if prereq_mod_id in modules:
                        prereq_graph[prereq_mod_id].append(mod_id)
                        in_degree[mod_id] += 1
            
            # Topological sort (Kahn's algorithm) with score-based tie-breaking
            # Modules with no prerequisites come first, ordered by score
            score_map = {r.item_id: r.score for r in recommendations}
            
            # Priority queue: (negative_score, module_id) - negative for max-heap behavior
            ready_modules = []
            for mod_id in module_ids:
                if in_degree[mod_id] == 0:
                    ready_modules.append((-score_map.get(mod_id, 0), mod_id))
            ready_modules.sort()
            
            ordered_sequence = []
            estimated_skill_gains = defaultdict(float)
            
            while ready_modules and len(ordered_sequence) < max_modules:
                # Get highest scoring ready module
                _, current_mod_id = ready_modules.pop(0)
                
                if current_mod_id not in modules:
                    continue
                    
                module = modules[current_mod_id]
                rec = next((r for r in recommendations if r.item_id == current_mod_id), None)
                
                if rec:
                    # Calculate estimated skill gains from this module
                    for ms in module.skill_mappings.all():
                        skill_name = ms.skill.name
                        estimated_skill_gains[skill_name] += ms.proficiency_gained
                    
                    ordered_sequence.append({
                        'position': len(ordered_sequence) + 1,
                        'module_id': current_mod_id,
                        'module_title': module.title,
                        'course_id': str(module.course_id),
                        'course_title': module.course.title if hasattr(module, 'course') else '',
                        'score': rec.score,
                        'reason': rec.reason,
                        'skills_developed': [
                            {
                                'skill_name': ms.skill.name,
                                'proficiency_gained': ms.proficiency_gained,
                                'contribution_level': ms.contribution_level
                            }
                            for ms in module.skill_mappings.all()[:3]
                        ]
                    })
                
                # Reduce in-degree for dependent modules
                for dependent_id in prereq_graph[current_mod_id]:
                    in_degree[dependent_id] -= 1
                    if in_degree[dependent_id] == 0:
                        ready_modules.append((-score_map.get(dependent_id, 0), dependent_id))
                        ready_modules.sort()
            
            # Compute summary of skill gains
            skill_gains_summary = {
                skill: round(min(gain, 100), 1)  # Cap at 100
                for skill, gain in estimated_skill_gains.items()
            }
            
            logger.info(
                f"Generated module sequence for user {user.id}: "
                f"{len(ordered_sequence)} modules"
            )
            
            return {
                'sequence': ordered_sequence,
                'total_modules': len(ordered_sequence),
                'estimated_skill_gains': skill_gains_summary,
                'skill_gap_analysis': skill_gaps[:5],  # Top 5 skill gaps
                'message': 'Learning sequence generated successfully'
            }
            
        except Exception as e:
            logger.error(
                f"Error generating module sequence for user {user.id}: {e}",
                exc_info=True
            )
            return {
                'sequence': [],
                'total_modules': 0,
                'estimated_skill_gains': {},
                'skill_gap_analysis': [],
                'message': f'Error generating sequence: {str(e)}'
            }

    @staticmethod
    def get_module_skill_gap_analysis(user: User, target_skills: list[str] = None) -> list:
        """
        Analyze skill gaps and recommend modules to address them.
        
        Provides a detailed breakdown of the user's skill gaps and which
        modules would best help to close those gaps.
        
        Args:
            user: The user to analyze
            target_skills: Optional list of skill IDs to focus analysis on
        
        Returns:
            List of skill gap analyses with recommended modules
        """
        from .recommenders import ModuleRecommender
        
        try:
            recommender = ModuleRecommender(
                user=user,
                target_skills=target_skills or []
            )
            
            gaps = recommender.get_skill_gap_analysis(target_skills)
            
            logger.info(f"Generated skill gap analysis for user {user.id}: {len(gaps)} skills analyzed")
            return gaps
            
        except Exception as e:
            logger.error(f"Error generating skill gap analysis for user {user.id}: {e}", exc_info=True)
            return []

    @staticmethod
    def identify_at_risk_students(
        course_id: str = None,
        tenant_id: str = None,
        limit: int = 50
    ) -> list:
        """
        Identify students who may be at risk of dropping out or failing.
        
        Uses ML-based risk prediction analyzing engagement patterns,
        assessment performance, and temporal features.
        
        Args:
            course_id: Optional course ID to filter by
            tenant_id: Optional tenant ID to filter by
            limit: Maximum number of at-risk students to return
            
        Returns:
            List of at-risk student data dictionaries, sorted by risk level
        """
        from .recommenders import get_risk_predictor
        
        try:
            predictor = get_risk_predictor()
            
            # Fit if needed
            if not predictor._model_fitted:
                predictor.fit(tenant_id=tenant_id)
            
            at_risk = predictor.get_at_risk_students(
                course_id=course_id,
                tenant_id=tenant_id,
                limit=limit
            )
            
            logger.info(f"Identified {len(at_risk)} at-risk students")
            return at_risk
            
        except ImportError:
            logger.warning("Risk predictor not available")
            return []
        except Exception as e:
            logger.error(f"Error identifying at-risk students: {e}", exc_info=True)
            return []

    @staticmethod
    def get_student_risk_assessment(user: User, course_id: str = None) -> dict:
        """
        Get detailed risk assessment for a specific student.
        
        Args:
            user: The user to assess
            course_id: Optional specific course to assess risk for
            
        Returns:
            Dictionary with risk score, level, factors, and recommendations
        """
        from .recommenders import get_risk_predictor
        
        try:
            predictor = get_risk_predictor()
            
            if not predictor._model_fitted:
                predictor.fit()
            
            return predictor.predict_risk(str(user.id), course_id)
            
        except ImportError:
            logger.warning("Risk predictor not available")
            return {
                'risk_score': 0.0,
                'risk_level': 'unknown',
                'factors': [],
                'message': 'Risk prediction not available'
            }
        except Exception as e:
            logger.error(f"Error getting student risk assessment: {e}", exc_info=True)
            return {
                'risk_score': 0.0,
                'risk_level': 'unknown',
                'factors': [],
                'message': f'Error: {str(e)}'
            }

    @staticmethod
    def get_performance_insights(user: User) -> dict:
        """
        Analyze user's assessment performance to identify strengths and weaknesses.
        
        Args:
            user: The user to analyze
            
        Returns:
            Dict with performance breakdown by course/category and weak areas
        """
        from apps.assessments.models import AssessmentAttempt, Assessment
        from apps.courses.models import Course
        from django.db.models import Avg, Count, F, Q
        from decimal import Decimal
        
        try:
            # Get all graded attempts for the user
            attempts = AssessmentAttempt.objects.filter(
                user=user,
                status=AssessmentAttempt.AttemptStatus.GRADED,
                max_score__gt=0
            ).select_related('assessment__course')
            
            if not attempts.exists():
                return {
                    'has_data': False,
                    'message': 'No completed assessments found',
                    'course_performance': [],
                    'category_performance': [],
                    'weak_areas': [],
                    'strong_areas': [],
                    'overall_stats': {}
                }
            
            # Calculate overall statistics
            total_attempts = attempts.count()
            passed_attempts = attempts.filter(is_passed=True).count()
            failed_attempts = attempts.filter(is_passed=False).count()
            
            # Calculate average score percentage
            scores = []
            for attempt in attempts:
                if attempt.score is not None and attempt.max_score > 0:
                    score_pct = float(attempt.score) / float(attempt.max_score) * 100
                    scores.append(score_pct)
            
            avg_score = sum(scores) / len(scores) if scores else 0
            
            overall_stats = {
                'total_attempts': total_attempts,
                'passed': passed_attempts,
                'failed': failed_attempts,
                'pass_rate': round(passed_attempts / total_attempts * 100, 1) if total_attempts > 0 else 0,
                'average_score': round(avg_score, 1)
            }
            
            # Performance by course
            course_stats = {}
            for attempt in attempts:
                course = attempt.assessment.course
                course_id = str(course.id)
                
                if course_id not in course_stats:
                    course_stats[course_id] = {
                        'course_id': course_id,
                        'course_title': course.title,
                        'course_slug': course.slug,
                        'category': course.category or 'Uncategorized',
                        'attempts': 0,
                        'passed': 0,
                        'total_score': 0,
                        'total_max_score': 0
                    }
                
                course_stats[course_id]['attempts'] += 1
                if attempt.is_passed:
                    course_stats[course_id]['passed'] += 1
                if attempt.score is not None:
                    course_stats[course_id]['total_score'] += float(attempt.score)
                if attempt.max_score:
                    course_stats[course_id]['total_max_score'] += attempt.max_score
            
            # Calculate percentages and classify
            course_performance = []
            weak_areas = []
            strong_areas = []
            
            for course_id, stats in course_stats.items():
                if stats['total_max_score'] > 0:
                    avg_pct = stats['total_score'] / stats['total_max_score'] * 100
                else:
                    avg_pct = 0
                    
                pass_rate = stats['passed'] / stats['attempts'] * 100 if stats['attempts'] > 0 else 0
                
                course_data = {
                    'course_id': course_id,
                    'course_title': stats['course_title'],
                    'course_slug': stats['course_slug'],
                    'category': stats['category'],
                    'attempts': stats['attempts'],
                    'passed': stats['passed'],
                    'average_score': round(avg_pct, 1),
                    'pass_rate': round(pass_rate, 1)
                }
                course_performance.append(course_data)
                
                # Classify as weak or strong area
                if avg_pct < 60 or pass_rate < 50:
                    weak_areas.append({
                        **course_data,
                        'severity': 'high' if avg_pct < 40 else 'medium',
                        'suggestion': f'Consider reviewing "{stats["course_title"]}" material'
                    })
                elif avg_pct >= 80 and pass_rate >= 80:
                    strong_areas.append(course_data)
            
            # Performance by category
            category_stats = {}
            for stats in course_stats.values():
                cat = stats['category']
                if cat not in category_stats:
                    category_stats[cat] = {
                        'category': cat,
                        'attempts': 0,
                        'passed': 0,
                        'total_score': 0,
                        'total_max_score': 0
                    }
                category_stats[cat]['attempts'] += stats['attempts']
                category_stats[cat]['passed'] += stats['passed']
                category_stats[cat]['total_score'] += stats['total_score']
                category_stats[cat]['total_max_score'] += stats['total_max_score']
            
            category_performance = []
            for cat, stats in category_stats.items():
                if stats['total_max_score'] > 0:
                    avg_pct = stats['total_score'] / stats['total_max_score'] * 100
                else:
                    avg_pct = 0
                pass_rate = stats['passed'] / stats['attempts'] * 100 if stats['attempts'] > 0 else 0
                
                category_performance.append({
                    'category': cat,
                    'attempts': stats['attempts'],
                    'passed': stats['passed'],
                    'average_score': round(avg_pct, 1),
                    'pass_rate': round(pass_rate, 1)
                })
            
            # Sort by performance
            course_performance.sort(key=lambda x: x['average_score'], reverse=True)
            category_performance.sort(key=lambda x: x['average_score'], reverse=True)
            weak_areas.sort(key=lambda x: x['average_score'])
            
            logger.info(f"Generated performance insights for user {user.id}: {len(weak_areas)} weak areas identified")
            
            return {
                'has_data': True,
                'course_performance': course_performance,
                'category_performance': category_performance,
                'weak_areas': weak_areas,
                'strong_areas': strong_areas,
                'overall_stats': overall_stats
            }
            
        except Exception as e:
            logger.error(f"Error generating performance insights for user {user.id}: {e}", exc_info=True)
            return {
                'has_data': False,
                'message': f'Error analyzing performance: {str(e)}',
                'course_performance': [],
                'category_performance': [],
                'weak_areas': [],
                'strong_areas': [],
                'overall_stats': {}
            }

    @staticmethod
    def get_skill_gaps(user: User) -> list:
        """
        Identify skill gaps based on failed assessments and low performance.
        
        Args:
            user: The user to analyze
            
        Returns:
            List of skill gaps with recommended actions
        """
        from apps.assessments.models import AssessmentAttempt, Assessment, Question
        from apps.courses.models import Course
        from django.db.models import Q, F
        from decimal import Decimal
        from collections import defaultdict
        
        try:
            # Get failed or low-scoring attempts (below 70%)
            poor_attempts = AssessmentAttempt.objects.filter(
                user=user,
                status=AssessmentAttempt.AttemptStatus.GRADED
            ).filter(
                Q(is_passed=False) | 
                Q(score__lt=F('max_score') * Decimal('0.7'))
            ).select_related('assessment__course').order_by('-created_at')[:50]
            
            if not poor_attempts.exists():
                return []
            
            skill_gaps = []
            course_gap_map = defaultdict(lambda: {
                'failed_assessments': 0,
                'assessment_titles': [],
                'last_attempt': None
            })
            
            for attempt in poor_attempts:
                assessment = attempt.assessment
                course = assessment.course
                course_id = str(course.id)
                
                course_gap_map[course_id]['course_id'] = course_id
                course_gap_map[course_id]['course_title'] = course.title
                course_gap_map[course_id]['course_slug'] = course.slug
                course_gap_map[course_id]['category'] = course.category or 'Uncategorized'
                course_gap_map[course_id]['failed_assessments'] += 1
                
                if assessment.title not in course_gap_map[course_id]['assessment_titles']:
                    course_gap_map[course_id]['assessment_titles'].append(assessment.title)
                
                if course_gap_map[course_id]['last_attempt'] is None:
                    course_gap_map[course_id]['last_attempt'] = attempt.created_at
                    
                    # Calculate score percentage for this attempt
                    if attempt.max_score and attempt.max_score > 0:
                        score_pct = float(attempt.score or 0) / float(attempt.max_score) * 100
                        course_gap_map[course_id]['last_score'] = round(score_pct, 1)
                    else:
                        course_gap_map[course_id]['last_score'] = 0
            
            # Build skill gaps list
            for course_id, gap_data in course_gap_map.items():
                severity = 'high' if gap_data['failed_assessments'] >= 3 else 'medium' if gap_data['failed_assessments'] >= 2 else 'low'
                
                skill_gaps.append({
                    'course_id': gap_data['course_id'],
                    'course_title': gap_data['course_title'],
                    'course_slug': gap_data['course_slug'],
                    'category': gap_data['category'],
                    'failed_assessments': gap_data['failed_assessments'],
                    'assessment_titles': gap_data['assessment_titles'][:3],  # Limit to 3
                    'last_score': gap_data.get('last_score', 0),
                    'severity': severity,
                    'recommendation': f'Review course materials and retake assessments for "{gap_data["course_title"]}"'
                })
            
            # Sort by severity (high first) and number of failed assessments
            severity_order = {'high': 0, 'medium': 1, 'low': 2}
            skill_gaps.sort(key=lambda x: (severity_order[x['severity']], -x['failed_assessments']))
            
            logger.info(f"Identified {len(skill_gaps)} skill gaps for user {user.id}")
            return skill_gaps
            
        except Exception as e:
            logger.error(f"Error identifying skill gaps for user {user.id}: {e}", exc_info=True)
            return []

    @staticmethod
    def get_remedial_recommendations(user: User, context: dict = None) -> list:
        """
        Generate remedial content recommendations based on assessment performance.
        Suggests content to review based on poor assessment performance.
        
        Args:
            user: The user to generate recommendations for
            context: Optional context dict with 'limit', 'assessment_id' (for specific assessment)
            
        Returns:
            List of remedial content recommendations
        """
        from apps.assessments.models import AssessmentAttempt, Assessment
        from apps.courses.models import Course, Module, ContentItem
        from apps.enrollments.models import Enrollment
        from django.db.models import Q, F
        from decimal import Decimal
        
        context = context or {}
        limit = context.get('limit', 10)
        specific_assessment_id = context.get('assessment_id')
        
        try:
            recommendations = []
            
            # Build query for poor attempts
            attempt_query = AssessmentAttempt.objects.filter(
                user=user,
                status=AssessmentAttempt.AttemptStatus.GRADED
            )
            
            if specific_assessment_id:
                # Get remedial content for a specific assessment
                attempt_query = attempt_query.filter(assessment_id=specific_assessment_id)
            else:
                # Get recent poor attempts (failed or below 70%)
                attempt_query = attempt_query.filter(
                    Q(is_passed=False) | 
                    Q(score__lt=F('max_score') * Decimal('0.7'))
                )
            
            poor_attempts = attempt_query.select_related(
                'assessment__course'
            ).order_by('-created_at')[:20]
            
            if not poor_attempts.exists():
                return []
            
            # Collect courses that need remediation
            courses_to_review = {}
            
            for attempt in poor_attempts:
                course = attempt.assessment.course
                course_id = str(course.id)
                
                if course_id not in courses_to_review:
                    # Calculate score percentage
                    if attempt.max_score and attempt.max_score > 0:
                        score_pct = float(attempt.score or 0) / float(attempt.max_score) * 100
                    else:
                        score_pct = 0
                    
                    courses_to_review[course_id] = {
                        'course': course,
                        'assessment_title': attempt.assessment.title,
                        'score_percentage': score_pct,
                        'is_passed': attempt.is_passed
                    }
            
            # Generate remedial content recommendations for each course
            for course_id, course_data in courses_to_review.items():
                course = course_data['course']
                
                # Get modules and content items from the course
                modules = Module.objects.filter(
                    course=course
                ).prefetch_related('content_items').order_by('order')
                
                for module in modules:
                    # Get published content items (videos, documents, text)
                    content_items = module.content_items.filter(
                        is_published=True
                    ).exclude(
                        content_type=ContentItem.ContentType.QUIZ
                    ).order_by('order')[:3]  # Limit per module
                    
                    for item in content_items:
                        # Determine priority based on score
                        if course_data['score_percentage'] < 40:
                            priority = 'high'
                            reason = f'Critical review needed - scored {course_data["score_percentage"]:.0f}% on "{course_data["assessment_title"]}"'
                        elif course_data['score_percentage'] < 60:
                            priority = 'medium'
                            reason = f'Review recommended - scored {course_data["score_percentage"]:.0f}% on "{course_data["assessment_title"]}"'
                        else:
                            priority = 'low'
                            reason = f'Optional review - scored {course_data["score_percentage"]:.0f}% on "{course_data["assessment_title"]}"'
                        
                        recommendations.append({
                            'type': 'content_item',
                            'id': str(item.id),
                            'title': item.title,
                            'content_type': item.content_type,
                            'module_id': str(module.id),
                            'module_title': module.title,
                            'course_id': str(course.id),
                            'course_title': course.title,
                            'course_slug': course.slug,
                            'priority': priority,
                            'reason': reason,
                            'related_assessment': course_data['assessment_title']
                        })
                
                # Also recommend revisiting the course itself
                priority = 'high' if course_data['score_percentage'] < 50 else 'medium'
                recommendations.append({
                    'type': 'course_review',
                    'id': str(course.id),
                    'title': course.title,
                    'course_slug': course.slug,
                    'category': course.category or 'Uncategorized',
                    'priority': priority,
                    'reason': f'Comprehensive review recommended after {course_data["assessment_title"]}',
                    'score_achieved': round(course_data['score_percentage'], 1),
                    'related_assessment': course_data['assessment_title']
                })
            
            # Sort by priority
            priority_order = {'high': 0, 'medium': 1, 'low': 2}
            recommendations.sort(key=lambda x: priority_order.get(x.get('priority', 'low'), 3))
            
            logger.info(f"Generated {len(recommendations)} remedial recommendations for user {user.id}")
            return recommendations[:limit]
            
        except Exception as e:
            logger.error(f"Error generating remedial recommendations for user {user.id}: {e}", exc_info=True)
            return []

    @staticmethod
    def get_learning_pace_analysis(user: User) -> dict:
        """
        Analyze user's learning pace compared to average learners.
        
        Args:
            user: The user to analyze
            
        Returns:
            Dict with learning pace metrics and comparisons
        """
        from apps.assessments.models import AssessmentAttempt
        from apps.enrollments.models import Enrollment
        from apps.progress.models import ContentProgress
        from django.db.models import Avg, Count, F
        from django.utils import timezone
        from datetime import timedelta
        
        try:
            # Calculate user's assessment completion rate
            user_attempts = AssessmentAttempt.objects.filter(
                user=user,
                status=AssessmentAttempt.AttemptStatus.GRADED
            )
            
            user_attempt_count = user_attempts.count()
            
            if user_attempt_count == 0:
                return {
                    'has_data': False,
                    'message': 'Not enough data to analyze learning pace'
                }
            
            # Calculate average time to complete assessments (in seconds)
            user_avg_duration = None
            durations = []
            for attempt in user_attempts:
                duration = attempt.calculate_duration()
                if duration is not None and duration > 0:
                    durations.append(duration)
            
            if durations:
                user_avg_duration = sum(durations) / len(durations)
            
            # Get global average duration for comparison
            all_attempts = AssessmentAttempt.objects.filter(
                status=AssessmentAttempt.AttemptStatus.GRADED,
                end_time__isnull=False
            ).exclude(user=user)
            
            global_durations = []
            for attempt in all_attempts[:500]:  # Limit for performance
                duration = attempt.calculate_duration()
                if duration is not None and duration > 0:
                    global_durations.append(duration)
            
            global_avg_duration = sum(global_durations) / len(global_durations) if global_durations else None
            
            # Calculate pace comparison
            pace_comparison = None
            pace_description = 'average'
            
            if user_avg_duration and global_avg_duration:
                pace_diff_pct = ((global_avg_duration - user_avg_duration) / global_avg_duration) * 100
                pace_comparison = round(pace_diff_pct, 1)
                
                if pace_diff_pct > 20:
                    pace_description = 'faster'
                elif pace_diff_pct < -20:
                    pace_description = 'slower'
                else:
                    pace_description = 'average'
            
            # Analyze content completion pace
            thirty_days_ago = timezone.now() - timedelta(days=30)
            
            try:
                user_content_completed = ContentProgress.objects.filter(
                    user=user,
                    is_completed=True,
                    completed_at__gte=thirty_days_ago
                ).count()
            except Exception:
                user_content_completed = 0
            
            # Get average content completion for all users in last 30 days
            try:
                avg_content_per_user = ContentProgress.objects.filter(
                    is_completed=True,
                    completed_at__gte=thirty_days_ago
                ).values('user').annotate(
                    completed_count=Count('id')
                ).aggregate(avg=Avg('completed_count'))['avg'] or 0
            except Exception:
                avg_content_per_user = 0
            
            content_pace_diff = None
            if avg_content_per_user > 0:
                content_pace_diff = round(((user_content_completed - avg_content_per_user) / avg_content_per_user) * 100, 1)
            
            return {
                'has_data': True,
                'assessment_pace': {
                    'user_avg_duration_seconds': round(user_avg_duration, 0) if user_avg_duration else None,
                    'user_avg_duration_minutes': round(user_avg_duration / 60, 1) if user_avg_duration else None,
                    'global_avg_duration_seconds': round(global_avg_duration, 0) if global_avg_duration else None,
                    'global_avg_duration_minutes': round(global_avg_duration / 60, 1) if global_avg_duration else None,
                    'pace_difference_percentage': pace_comparison,
                    'pace_description': pace_description,
                    'total_assessments_completed': user_attempt_count
                },
                'content_pace': {
                    'items_completed_30_days': user_content_completed,
                    'average_items_per_user': round(avg_content_per_user, 1),
                    'pace_difference_percentage': content_pace_diff
                },
                'insights': PersonalizationService._generate_pace_insights(
                    pace_description, pace_comparison, content_pace_diff
                )
            }
            
        except Exception as e:
            logger.error(f"Error analyzing learning pace for user {user.id}: {e}", exc_info=True)
            return {
                'has_data': False,
                'message': f'Error analyzing learning pace: {str(e)}'
            }

    @staticmethod
    def _generate_pace_insights(pace_description: str, pace_diff: float | None, content_diff: float | None) -> list:
        """Generate human-readable insights about learning pace."""
        insights = []
        
        if pace_description == 'faster' and pace_diff:
            insights.append({
                'type': 'positive',
                'message': f"You complete assessments {abs(pace_diff):.0f}% faster than average learners",
                'icon': 'zap'
            })
        elif pace_description == 'slower' and pace_diff:
            insights.append({
                'type': 'neutral',
                'message': f"You take {abs(pace_diff):.0f}% more time on assessments than average, which can lead to more thorough understanding",
                'icon': 'clock'
            })
        else:
            insights.append({
                'type': 'neutral',
                'message': "Your assessment completion pace is similar to other learners",
                'icon': 'check'
            })
        
        if content_diff is not None:
            if content_diff > 50:
                insights.append({
                    'type': 'positive',
                    'message': f"You're completing {content_diff:.0f}% more content than average in the last 30 days",
                    'icon': 'trending-up'
                })
            elif content_diff < -30:
                insights.append({
                    'type': 'suggestion',
                    'message': "Consider setting aside dedicated study time to increase your learning momentum",
                    'icon': 'calendar'
                })
        
        return insights


class NLPProcessorService:
    """Service for NLP tasks like text analysis, keyword extraction, summarization."""

    # Common English stop words for keyword extraction
    STOP_WORDS = {
        'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
        'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
        'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need',
        'it', 'its', 'this', 'that', 'these', 'those', 'i', 'you', 'he',
        'she', 'we', 'they', 'what', 'which', 'who', 'whom', 'whose',
        'where', 'when', 'why', 'how', 'all', 'each', 'every', 'both',
        'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not',
        'only', 'own', 'same', 'so', 'than', 'too', 'very', 'just', 'also',
        'now', 'here', 'there', 'then', 'once', 'if', 'about', 'into',
        'through', 'during', 'before', 'after', 'above', 'below', 'between',
        'under', 'again', 'further', 'while', 'any', 'because', 'being',
        'etc', 'even', 'get', 'got', 'him', 'her', 'his', 'my', 'our',
        'out', 'over', 'their', 'them', 'up', 'your', 'much', 'many'
    }

    # Simple sentiment word lists
    POSITIVE_WORDS = {
        'good', 'great', 'excellent', 'amazing', 'wonderful', 'fantastic',
        'outstanding', 'superb', 'brilliant', 'awesome', 'love', 'best',
        'happy', 'helpful', 'useful', 'easy', 'perfect', 'beautiful',
        'nice', 'positive', 'success', 'successful', 'effective', 'well',
        'better', 'improved', 'recommend', 'enjoyed', 'thank', 'thanks'
    }

    NEGATIVE_WORDS = {
        'bad', 'terrible', 'awful', 'horrible', 'poor', 'worst', 'hate',
        'difficult', 'hard', 'confusing', 'boring', 'slow', 'broken',
        'failed', 'failure', 'problem', 'issue', 'bug', 'error', 'wrong',
        'negative', 'disappointed', 'disappointing', 'frustrating', 'useless',
        'waste', 'never', 'cannot', 'unfortunately', 'lacking', 'missing'
    }

    @staticmethod
    def analyze_text(text: str, options: dict = None) -> dict:
        """
        Analyze text for keywords, sentiment, readability, and generate a summary.
        
        Args:
            text: The text to analyze
            options: Optional dict with keys:
                - 'max_keywords': Maximum number of keywords to extract (default 10)
                - 'summary_sentences': Number of sentences for summary (default 3)
                - 'include_sentiment': Whether to analyze sentiment (default True)
                - 'include_readability': Whether to calculate readability (default True)
        
        Returns:
            Dict with 'keywords', 'summary', 'sentiment', 'readability', 'word_count', 'stats'
        """
        import re
        from collections import Counter
        
        options = options or {}
        max_keywords = options.get('max_keywords', 10)
        summary_sentences = options.get('summary_sentences', 3)
        include_sentiment = options.get('include_sentiment', True)
        include_readability = options.get('include_readability', True)
        
        if not text or not text.strip():
            return {
                'keywords': [],
                'summary': '',
                'sentiment': None,
                'readability': None,
                'word_count': 0,
                'stats': {}
            }
        
        # Clean and normalize text
        clean_text = text.strip()
        
        # Basic text statistics
        sentences = re.split(r'[.!?]+', clean_text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        # Tokenize words (simple approach)
        words = re.findall(r'\b[a-zA-Z]{2,}\b', clean_text.lower())
        word_count = len(words)
        
        # Extract keywords using TF (term frequency) approach
        keywords = NLPProcessorService._extract_keywords(words, max_keywords)
        
        # Generate extractive summary
        summary = NLPProcessorService._generate_summary(sentences, keywords, summary_sentences)
        
        # Sentiment analysis
        sentiment = None
        if include_sentiment:
            sentiment = NLPProcessorService._analyze_sentiment(words)
        
        # Readability analysis
        readability = None
        if include_readability:
            readability = NLPProcessorService._calculate_readability(clean_text, sentences, words)
        
        # Additional statistics
        stats = {
            'sentence_count': len(sentences),
            'word_count': word_count,
            'avg_sentence_length': round(word_count / max(len(sentences), 1), 1),
            'unique_words': len(set(words)),
            'lexical_diversity': round(len(set(words)) / max(word_count, 1), 3)
        }
        
        logger.info(f"NLP analysis completed: {word_count} words, {len(keywords)} keywords extracted")
        
        return {
            'keywords': keywords,
            'summary': summary,
            'sentiment': sentiment,
            'readability': readability,
            'word_count': word_count,
            'stats': stats
        }

    @staticmethod
    def _extract_keywords(words: list, max_keywords: int) -> list:
        """Extract keywords using term frequency, excluding stop words."""
        from collections import Counter
        
        # Filter out stop words and short words
        filtered_words = [
            w for w in words 
            if w not in NLPProcessorService.STOP_WORDS and len(w) > 2
        ]
        
        # Count word frequencies
        word_freq = Counter(filtered_words)
        
        # Get top keywords with their scores
        total_words = len(filtered_words) if filtered_words else 1
        keywords = []
        
        for word, count in word_freq.most_common(max_keywords):
            keywords.append({
                'word': word,
                'count': count,
                'score': round(count / total_words, 4)
            })
        
        return keywords

    @staticmethod
    def _generate_summary(sentences: list, keywords: list, num_sentences: int) -> str:
        """Generate extractive summary by scoring sentences based on keyword presence."""
        if not sentences:
            return ''
        
        if len(sentences) <= num_sentences:
            return ' '.join(sentences)
        
        keyword_set = {kw['word'] for kw in keywords}
        
        # Score each sentence by keyword presence
        scored_sentences = []
        for i, sentence in enumerate(sentences):
            words = set(sentence.lower().split())
            score = len(words & keyword_set)
            # Boost first sentence (often contains important info)
            if i == 0:
                score += 2
            scored_sentences.append((i, sentence, score))
        
        # Sort by score, take top sentences, then reorder by position
        top_sentences = sorted(scored_sentences, key=lambda x: x[2], reverse=True)[:num_sentences]
        top_sentences = sorted(top_sentences, key=lambda x: x[0])  # Restore original order
        
        return ' '.join(s[1] for s in top_sentences)

    @staticmethod
    def _analyze_sentiment(words: list) -> dict:
        """Simple sentiment analysis based on word lists."""
        positive_count = sum(1 for w in words if w in NLPProcessorService.POSITIVE_WORDS)
        negative_count = sum(1 for w in words if w in NLPProcessorService.NEGATIVE_WORDS)
        
        total_sentiment_words = positive_count + negative_count
        
        if total_sentiment_words == 0:
            label = 'neutral'
            score = 0.0
        else:
            # Score from -1 (negative) to 1 (positive)
            score = (positive_count - negative_count) / total_sentiment_words
            
            if score > 0.2:
                label = 'positive'
            elif score < -0.2:
                label = 'negative'
            else:
                label = 'neutral'
        
        return {
            'label': label,
            'score': round(score, 3),
            'positive_count': positive_count,
            'negative_count': negative_count,
            'confidence': round(total_sentiment_words / max(len(words), 1), 3)
        }

    @staticmethod
    def _calculate_readability(text: str, sentences: list, words: list) -> dict:
        """Calculate readability metrics (Flesch-Kincaid, etc.)."""
        import re
        
        if not words or not sentences:
            return {
                'flesch_reading_ease': None,
                'flesch_kincaid_grade': None,
                'level': 'unknown'
            }
        
        # Count syllables (simplified estimation)
        def count_syllables(word):
            word = word.lower()
            if len(word) <= 3:
                return 1
            # Count vowel groups
            count = len(re.findall(r'[aeiouy]+', word))
            # Adjust for silent e
            if word.endswith('e'):
                count -= 1
            return max(count, 1)
        
        total_syllables = sum(count_syllables(w) for w in words)
        total_words = len(words)
        total_sentences = len(sentences)
        
        # Flesch Reading Ease
        # 206.835 - 1.015 * (words/sentences) - 84.6 * (syllables/words)
        avg_sentence_length = total_words / total_sentences
        avg_syllables_per_word = total_syllables / total_words
        
        flesch_reading_ease = (
            206.835 
            - (1.015 * avg_sentence_length) 
            - (84.6 * avg_syllables_per_word)
        )
        flesch_reading_ease = round(max(0, min(100, flesch_reading_ease)), 1)
        
        # Flesch-Kincaid Grade Level
        # 0.39 * (words/sentences) + 11.8 * (syllables/words) - 15.59
        flesch_kincaid_grade = (
            (0.39 * avg_sentence_length) 
            + (11.8 * avg_syllables_per_word) 
            - 15.59
        )
        flesch_kincaid_grade = round(max(0, flesch_kincaid_grade), 1)
        
        # Determine reading level
        if flesch_reading_ease >= 90:
            level = 'very_easy'  # 5th grade
        elif flesch_reading_ease >= 80:
            level = 'easy'  # 6th grade
        elif flesch_reading_ease >= 70:
            level = 'fairly_easy'  # 7th grade
        elif flesch_reading_ease >= 60:
            level = 'standard'  # 8th-9th grade
        elif flesch_reading_ease >= 50:
            level = 'fairly_difficult'  # 10th-12th grade
        elif flesch_reading_ease >= 30:
            level = 'difficult'  # College
        else:
            level = 'very_difficult'  # College graduate
        
        return {
            'flesch_reading_ease': flesch_reading_ease,
            'flesch_kincaid_grade': flesch_kincaid_grade,
            'avg_syllables_per_word': round(avg_syllables_per_word, 2),
            'level': level
        }


class EvaluationService:
    """Service for evaluating the quality of generated content."""

    # Minimum thresholds for quality checks
    MIN_WORD_COUNT = 10
    MAX_WORD_COUNT = 10000
    MIN_SENTENCE_LENGTH = 3
    MAX_SENTENCE_LENGTH = 100
    MIN_UNIQUE_WORD_RATIO = 0.3  # At least 30% unique words
    
    # Patterns that may indicate low-quality content
    REPETITION_THRESHOLD = 5  # Max times a phrase can repeat
    
    # Inappropriate content patterns (basic)
    INAPPROPRIATE_PATTERNS = [
        r'\b(placeholder|lorem ipsum|todo|fixme|xxx)\b',
        r'\[.*?insert.*?\]',
        r'<.*?placeholder.*?>',
    ]

    @staticmethod
    def evaluate_content(content: GeneratedContent, options: dict = None) -> dict:
        """
        Evaluate the quality of AI-generated content using multiple heuristics.
        
        Args:
            content: The GeneratedContent instance to evaluate
            options: Optional dict with keys:
                - 'strict': Use stricter evaluation thresholds (default False)
                - 'check_readability': Include readability analysis (default True)
                - 'context': Original context/prompt for relevance checking
        
        Returns:
            Dict with 'quality_score' (0-100), 'issues', 'metrics', 'passed'
        """
        import re
        from collections import Counter
        
        options = options or {}
        strict_mode = options.get('strict', False)
        check_readability = options.get('check_readability', True)
        original_context = options.get('context', {})
        
        issues = []
        metrics = {}
        
        # Get the generated text
        text = content.generated_text if content else ''
        
        if not text or not text.strip():
            return {
                'quality_score': 0,
                'issues': [{'type': 'empty_content', 'severity': 'critical', 'message': 'Generated content is empty'}],
                'metrics': {},
                'passed': False
            }
        
        clean_text = text.strip()
        
        # Basic text analysis
        sentences = re.split(r'[.!?]+', clean_text)
        sentences = [s.strip() for s in sentences if s.strip()]
        words = re.findall(r'\b[a-zA-Z]+\b', clean_text.lower())
        word_count = len(words)
        unique_words = set(words)
        
        # Initialize score (start at 100, deduct for issues)
        score = 100.0
        
        # Check 1: Word count
        metrics['word_count'] = word_count
        if word_count < EvaluationService.MIN_WORD_COUNT:
            issues.append({
                'type': 'too_short',
                'severity': 'warning',
                'message': f'Content is too short ({word_count} words, minimum {EvaluationService.MIN_WORD_COUNT})'
            })
            score -= 20
        elif word_count > EvaluationService.MAX_WORD_COUNT:
            issues.append({
                'type': 'too_long',
                'severity': 'info',
                'message': f'Content is very long ({word_count} words)'
            })
            score -= 5
        
        # Check 2: Sentence quality
        metrics['sentence_count'] = len(sentences)
        if sentences:
            avg_sentence_length = word_count / len(sentences)
            metrics['avg_sentence_length'] = round(avg_sentence_length, 1)
            
            # Check for overly short or long sentences
            short_sentences = sum(1 for s in sentences if len(s.split()) < EvaluationService.MIN_SENTENCE_LENGTH)
            long_sentences = sum(1 for s in sentences if len(s.split()) > EvaluationService.MAX_SENTENCE_LENGTH)
            
            if short_sentences > len(sentences) * 0.3:
                issues.append({
                    'type': 'fragmented',
                    'severity': 'warning',
                    'message': f'{short_sentences} sentences are too short (fragmented content)'
                })
                score -= 10
            
            if long_sentences > 0:
                issues.append({
                    'type': 'run_on_sentences',
                    'severity': 'info',
                    'message': f'{long_sentences} sentences are excessively long'
                })
                score -= 5 * long_sentences
        
        # Check 3: Vocabulary diversity
        if word_count > 0:
            unique_ratio = len(unique_words) / word_count
            metrics['unique_word_ratio'] = round(unique_ratio, 3)
            
            if unique_ratio < EvaluationService.MIN_UNIQUE_WORD_RATIO:
                issues.append({
                    'type': 'low_diversity',
                    'severity': 'warning',
                    'message': f'Low vocabulary diversity ({unique_ratio:.1%} unique words)'
                })
                score -= 15
        
        # Check 4: Repetition detection
        word_freq = Counter(words)
        most_common = word_freq.most_common(10)
        
        # Check for excessive repetition of non-stop words
        stop_words = NLPProcessorService.STOP_WORDS
        repeated_words = [
            (word, count) for word, count in most_common 
            if word not in stop_words and count > EvaluationService.REPETITION_THRESHOLD
        ]
        
        if repeated_words:
            metrics['repeated_words'] = repeated_words[:5]
            if len(repeated_words) > 3:
                issues.append({
                    'type': 'excessive_repetition',
                    'severity': 'warning',
                    'message': f'Excessive word repetition detected: {", ".join(w[0] for w in repeated_words[:3])}'
                })
                score -= 10
        
        # Check 5: Phrase/sentence repetition
        if len(sentences) > 2:
            sentence_freq = Counter(s.lower().strip() for s in sentences)
            duplicate_sentences = [(s, c) for s, c in sentence_freq.items() if c > 1]
            
            if duplicate_sentences:
                metrics['duplicate_sentences'] = len(duplicate_sentences)
                issues.append({
                    'type': 'duplicate_sentences',
                    'severity': 'warning',
                    'message': f'{len(duplicate_sentences)} sentences are repeated'
                })
                score -= 5 * len(duplicate_sentences)
        
        # Check 6: Inappropriate/placeholder content
        for pattern in EvaluationService.INAPPROPRIATE_PATTERNS:
            matches = re.findall(pattern, clean_text, re.IGNORECASE)
            if matches:
                issues.append({
                    'type': 'placeholder_content',
                    'severity': 'critical',
                    'message': f'Found placeholder/incomplete content: {matches[0]}'
                })
                score -= 25
                break
        
        # Check 7: Coherence indicators
        # Check if sentences start with variety
        if sentences:
            sentence_starts = [s.split()[0].lower() if s.split() else '' for s in sentences]
            start_freq = Counter(sentence_starts)
            most_common_start = start_freq.most_common(1)
            
            if most_common_start and most_common_start[0][1] > len(sentences) * 0.4:
                issues.append({
                    'type': 'monotonous_structure',
                    'severity': 'info',
                    'message': f'Many sentences start with "{most_common_start[0][0]}"'
                })
                score -= 5
        
        # Check 8: Readability (if enabled)
        if check_readability and word_count > 20:
            readability = NLPProcessorService._calculate_readability(clean_text, sentences, words)
            metrics['readability'] = readability
            
            # Penalize very difficult or very easy content (depending on context)
            if readability.get('flesch_reading_ease', 50) < 20:
                issues.append({
                    'type': 'very_difficult_reading',
                    'severity': 'info',
                    'message': 'Content has very difficult readability level'
                })
                score -= 5
        
        # Check 9: Metadata/generation context checks
        if content.metadata:
            metadata = content.metadata
            
            # Check if generation had errors or warnings
            if metadata.get('error'):
                issues.append({
                    'type': 'generation_error',
                    'severity': 'warning',
                    'message': f'Generation had errors: {metadata.get("error")}'
                })
                score -= 15
            
            # Check token usage efficiency
            if metadata.get('total_tokens') and metadata.get('completion_tokens'):
                completion_ratio = metadata['completion_tokens'] / metadata['total_tokens']
                metrics['completion_ratio'] = round(completion_ratio, 3)
        
        # Apply strict mode adjustments
        if strict_mode:
            # In strict mode, warnings become more impactful
            warning_count = sum(1 for i in issues if i['severity'] == 'warning')
            score -= warning_count * 5
        
        # Normalize score to 0-100
        score = max(0, min(100, score))
        
        # Determine pass/fail
        pass_threshold = 60 if strict_mode else 50
        passed = score >= pass_threshold and not any(i['severity'] == 'critical' for i in issues)
        
        logger.info(f"Content evaluation completed: score={score:.1f}, issues={len(issues)}, passed={passed}")
        
        return {
            'quality_score': round(score, 1),
            'issues': issues,
            'metrics': metrics,
            'passed': passed
        }

    @staticmethod
    def evaluate_batch(contents: list, options: dict = None) -> dict:
        """
        Evaluate multiple generated contents and provide aggregate statistics.
        
        Args:
            contents: List of GeneratedContent instances
            options: Evaluation options (passed to evaluate_content)
        
        Returns:
            Dict with 'results', 'summary' containing aggregate stats
        """
        results = []
        scores = []
        total_issues = 0
        passed_count = 0
        
        for content in contents:
            result = EvaluationService.evaluate_content(content, options)
            results.append({
                'content_id': str(content.id) if content else None,
                'evaluation': result
            })
            
            if result['quality_score'] is not None:
                scores.append(result['quality_score'])
            total_issues += len(result.get('issues', []))
            if result.get('passed'):
                passed_count += 1
        
        summary = {
            'total_evaluated': len(contents),
            'passed': passed_count,
            'failed': len(contents) - passed_count,
            'pass_rate': round(passed_count / max(len(contents), 1) * 100, 1),
            'avg_quality_score': round(sum(scores) / max(len(scores), 1), 1) if scores else None,
            'min_quality_score': min(scores) if scores else None,
            'max_quality_score': max(scores) if scores else None,
            'total_issues': total_issues
        }
        
        return {
            'results': results,
            'summary': summary
        }
