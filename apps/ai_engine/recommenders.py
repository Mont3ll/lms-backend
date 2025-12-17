"""
ML-based recommendation system for the LMS.

This module provides collaborative filtering, content-based filtering, and hybrid
recommendation algorithms to personalize course and content recommendations for users.
"""

import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from django.db.models import Avg, Count, F, Q
from django.utils import timezone
from scipy.sparse import csr_matrix
from sklearn.decomposition import TruncatedSVD
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import MinMaxScaler

logger = logging.getLogger(__name__)


@dataclass
class RecommendationResult:
    """Represents a single recommendation with metadata."""
    
    item_id: str
    item_type: str  # 'course', 'learning_path', 'content_item'
    title: str
    score: float
    reason: str
    metadata: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            'id': self.item_id,
            'type': self.item_type,
            'title': self.title,
            'score': round(self.score, 4),
            'reason': self.reason,
            **self.metadata
        }


class BaseRecommender(ABC):
    """Abstract base class for all recommender implementations."""
    
    def __init__(self, min_interactions: int = 5, cache_ttl: int = 3600):
        """
        Initialize the recommender.
        
        Args:
            min_interactions: Minimum number of interactions required to generate recommendations.
            cache_ttl: Cache time-to-live in seconds.
        """
        self.min_interactions = min_interactions
        self.cache_ttl = cache_ttl
        self._model_fitted = False
        self._last_fit_time = None
    
    @abstractmethod
    def fit(self, tenant_id: str = None) -> None:
        """Train the recommendation model on available data."""
        pass
    
    @abstractmethod
    def recommend(
        self, 
        user_id: str, 
        n_recommendations: int = 10,
        exclude_enrolled: bool = True
    ) -> list[RecommendationResult]:
        """Generate recommendations for a user."""
        pass
    
    def is_model_stale(self, max_age_hours: int = 24) -> bool:
        """Check if the model needs to be retrained."""
        if not self._model_fitted or self._last_fit_time is None:
            return True
        
        age = (timezone.now() - self._last_fit_time).total_seconds() / 3600
        return age > max_age_hours


class CollaborativeRecommender(BaseRecommender):
    """
    Collaborative filtering recommender using matrix factorization (SVD).
    
    This recommender analyzes user-course interaction patterns to find similar users
    and recommend courses that similar users have engaged with positively.
    """
    
    def __init__(
        self, 
        n_factors: int = 50, 
        min_interactions: int = 5,
        regularization: float = 0.1
    ):
        """
        Initialize the collaborative filtering recommender.
        
        Args:
            n_factors: Number of latent factors for matrix factorization.
            min_interactions: Minimum interactions required.
            regularization: Regularization parameter for SVD.
        """
        super().__init__(min_interactions=min_interactions)
        self.n_factors = n_factors
        self.regularization = regularization
        
        # Model components
        self._svd = None
        self._user_factors = None
        self._item_factors = None
        self._user_id_map = {}  # Maps user_id (UUID) to matrix index
        self._item_id_map = {}  # Maps course_id (UUID) to matrix index
        self._reverse_user_map = {}  # Maps matrix index to user_id
        self._reverse_item_map = {}  # Maps matrix index to course_id
        self._interaction_matrix = None
        self._global_mean = 0.0
        
        # Course metadata cache
        self._course_metadata = {}
    
    def fit(self, tenant_id: str = None) -> None:
        """
        Train the collaborative filtering model on enrollment and progress data.
        
        Args:
            tenant_id: Optional tenant ID to filter data by tenant.
        """
        from apps.courses.models import Course
        from apps.enrollments.models import Enrollment
        
        logger.info("Fitting collaborative filtering model...")
        
        # Build the user-item interaction matrix
        # Interaction score = weighted combination of:
        # - Enrollment (implicit positive signal)
        # - Progress percentage (higher = more interest)
        # - Completion (strong positive signal)
        
        enrollment_query = Enrollment.objects.filter(
            status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED]
        ).select_related('user', 'course')
        
        if tenant_id:
            enrollment_query = enrollment_query.filter(course__tenant_id=tenant_id)
        
        enrollments = list(enrollment_query)
        
        if len(enrollments) < self.min_interactions:
            logger.warning(
                f"Insufficient data for collaborative filtering: "
                f"{len(enrollments)} < {self.min_interactions}"
            )
            self._model_fitted = False
            return
        
        # Build ID mappings
        users = set()
        items = set()
        
        for enrollment in enrollments:
            users.add(str(enrollment.user_id))
            items.add(str(enrollment.course_id))
        
        self._user_id_map = {uid: idx for idx, uid in enumerate(sorted(users))}
        self._item_id_map = {iid: idx for idx, iid in enumerate(sorted(items))}
        self._reverse_user_map = {v: k for k, v in self._user_id_map.items()}
        self._reverse_item_map = {v: k for k, v in self._item_id_map.items()}
        
        n_users = len(self._user_id_map)
        n_items = len(self._item_id_map)
        
        # Build interaction scores
        # Score formula: base_score + progress_bonus + completion_bonus
        interactions = []
        row_indices = []
        col_indices = []
        
        for enrollment in enrollments:
            user_idx = self._user_id_map[str(enrollment.user_id)]
            item_idx = self._item_id_map[str(enrollment.course_id)]
            
            # Calculate interaction score (0-5 scale)
            base_score = 2.5  # Enrollment indicates interest
            progress_bonus = (enrollment.progress / 100) * 1.5  # Up to 1.5 bonus
            completion_bonus = 1.0 if enrollment.status == Enrollment.Status.COMPLETED else 0
            
            score = min(5.0, base_score + progress_bonus + completion_bonus)
            
            row_indices.append(user_idx)
            col_indices.append(item_idx)
            interactions.append(score)
        
        # Create sparse interaction matrix
        self._interaction_matrix = csr_matrix(
            (interactions, (row_indices, col_indices)),
            shape=(n_users, n_items)
        )
        
        self._global_mean = np.mean(interactions)
        
        # Apply SVD for matrix factorization
        # Use TruncatedSVD for sparse matrix compatibility
        actual_factors = min(self.n_factors, min(n_users, n_items) - 1)
        
        if actual_factors < 2:
            logger.warning("Insufficient dimensions for SVD, using simple similarity")
            self._model_fitted = False
            return
        
        self._svd = TruncatedSVD(n_components=actual_factors, random_state=42)
        
        # Center the matrix (subtract global mean from non-zero entries)
        centered_matrix = self._interaction_matrix.copy()
        centered_matrix.data -= self._global_mean
        
        # Fit SVD
        self._user_factors = self._svd.fit_transform(centered_matrix)
        self._item_factors = self._svd.components_.T
        
        # Cache course metadata for recommendations
        course_ids = list(self._item_id_map.keys())
        courses = Course.objects.filter(id__in=course_ids).values(
            'id', 'title', 'slug', 'description', 'category', 'difficulty_level'
        )
        
        self._course_metadata = {str(c['id']): c for c in courses}
        
        self._model_fitted = True
        self._last_fit_time = timezone.now()
        
        logger.info(
            f"Collaborative filtering model fitted: "
            f"{n_users} users, {n_items} items, {actual_factors} factors"
        )
    
    def recommend(
        self, 
        user_id: str, 
        n_recommendations: int = 10,
        exclude_enrolled: bool = True
    ) -> list[RecommendationResult]:
        """
        Generate course recommendations for a user using collaborative filtering.
        
        Args:
            user_id: The user's ID.
            n_recommendations: Number of recommendations to return.
            exclude_enrolled: Whether to exclude courses the user is already enrolled in.
            
        Returns:
            List of RecommendationResult objects.
        """
        from apps.enrollments.models import Enrollment
        
        if not self._model_fitted:
            logger.warning("Model not fitted, cannot generate recommendations")
            return []
        
        user_id_str = str(user_id)
        
        if user_id_str not in self._user_id_map:
            logger.info(f"User {user_id_str} not in training data, using cold-start strategy")
            return self._cold_start_recommendations(user_id, n_recommendations)
        
        user_idx = self._user_id_map[user_id_str]
        user_vector = self._user_factors[user_idx]
        
        # Calculate predicted scores for all items
        predicted_scores = np.dot(user_vector, self._item_factors.T) + self._global_mean
        
        # Get user's enrolled courses to exclude
        excluded_items = set()
        if exclude_enrolled:
            enrolled = Enrollment.objects.filter(user_id=user_id).values_list('course_id', flat=True)
            excluded_items = {str(cid) for cid in enrolled}
        
        # Build recommendations
        recommendations = []
        item_scores = []
        
        for item_idx, score in enumerate(predicted_scores):
            item_id = self._reverse_item_map[item_idx]
            if item_id not in excluded_items:
                item_scores.append((item_id, score))
        
        # Sort by predicted score
        item_scores.sort(key=lambda x: x[1], reverse=True)
        
        # Normalize scores to 0-1 range
        if item_scores:
            max_score = max(s for _, s in item_scores)
            min_score = min(s for _, s in item_scores)
            score_range = max_score - min_score if max_score != min_score else 1
        
        for item_id, raw_score in item_scores[:n_recommendations]:
            normalized_score = (raw_score - min_score) / score_range if score_range else 0.5
            
            metadata = self._course_metadata.get(item_id, {})
            
            recommendations.append(RecommendationResult(
                item_id=item_id,
                item_type='course',
                title=metadata.get('title', 'Unknown Course'),
                score=normalized_score,
                reason='Recommended based on learners with similar interests',
                metadata={
                    'slug': metadata.get('slug', ''),
                    'description': (metadata.get('description', '') or '')[:200],
                    'category': metadata.get('category', ''),
                    'difficulty_level': metadata.get('difficulty_level', ''),
                    'algorithm': 'collaborative_filtering'
                }
            ))
        
        return recommendations
    
    def _cold_start_recommendations(
        self, 
        user_id: str, 
        n_recommendations: int
    ) -> list[RecommendationResult]:
        """
        Generate recommendations for new users with no interaction history.
        
        Uses popularity-based recommendations as a fallback.
        """
        from apps.courses.models import Course
        from apps.enrollments.models import Enrollment
        
        # Get popular courses
        popular_courses = Course.objects.filter(
            status=Course.Status.PUBLISHED
        ).annotate(
            enrollment_count=Count('enrollments')
        ).order_by('-enrollment_count')[:n_recommendations]
        
        # Exclude already enrolled
        enrolled = set(
            str(cid) for cid in 
            Enrollment.objects.filter(user_id=user_id).values_list('course_id', flat=True)
        )
        
        recommendations = []
        for course in popular_courses:
            if str(course.id) in enrolled:
                continue
            
            recommendations.append(RecommendationResult(
                item_id=str(course.id),
                item_type='course',
                title=course.title,
                score=0.7,  # Default score for popular items
                reason='Popular with other learners',
                metadata={
                    'slug': course.slug,
                    'description': (course.description or '')[:200],
                    'category': course.category or '',
                    'difficulty_level': course.difficulty_level,
                    'enrollment_count': course.enrollment_count,
                    'algorithm': 'popularity_fallback'
                }
            ))
        
        return recommendations[:n_recommendations]
    
    def get_similar_users(self, user_id: str, n_similar: int = 10) -> list[tuple[str, float]]:
        """
        Find users with similar preferences.
        
        Args:
            user_id: The target user's ID.
            n_similar: Number of similar users to return.
            
        Returns:
            List of (user_id, similarity_score) tuples.
        """
        if not self._model_fitted:
            return []
        
        user_id_str = str(user_id)
        if user_id_str not in self._user_id_map:
            return []
        
        user_idx = self._user_id_map[user_id_str]
        user_vector = self._user_factors[user_idx].reshape(1, -1)
        
        # Calculate cosine similarity with all users
        similarities = cosine_similarity(user_vector, self._user_factors)[0]
        
        # Get top similar users (excluding self)
        similar_indices = np.argsort(similarities)[::-1]
        
        result = []
        for idx in similar_indices:
            if idx != user_idx and len(result) < n_similar:
                other_user_id = self._reverse_user_map[idx]
                result.append((other_user_id, float(similarities[idx])))
        
        return result


class ContentBasedRecommender(BaseRecommender):
    """
    Content-based filtering recommender.
    
    This recommender analyzes course attributes (category, tags, difficulty, etc.)
    to find courses similar to those a user has engaged with positively.
    """
    
    def __init__(self, min_interactions: int = 3):
        """
        Initialize the content-based recommender.
        
        Args:
            min_interactions: Minimum interactions required.
        """
        super().__init__(min_interactions=min_interactions)
        
        # Feature vectors for courses
        self._course_features = {}  # course_id -> feature vector
        self._feature_matrix = None
        self._course_id_list = []
        self._feature_names = []
        self._course_metadata = {}
    
    def fit(self, tenant_id: str = None) -> None:
        """
        Build feature vectors for all courses.
        
        Args:
            tenant_id: Optional tenant ID to filter data by tenant.
        """
        from apps.courses.models import Course
        
        logger.info("Fitting content-based recommendation model...")
        
        course_query = Course.objects.filter(status=Course.Status.PUBLISHED)
        
        if tenant_id:
            course_query = course_query.filter(tenant_id=tenant_id)
        
        courses = list(course_query.values(
            'id', 'title', 'slug', 'description', 'category', 
            'tags', 'difficulty_level', 'estimated_duration'
        ))
        
        if len(courses) < self.min_interactions:
            logger.warning(
                f"Insufficient courses for content-based filtering: "
                f"{len(courses)} < {self.min_interactions}"
            )
            self._model_fitted = False
            return
        
        # Build feature vocabulary
        categories = set()
        all_tags = set()
        difficulty_levels = set()
        
        for course in courses:
            if course['category']:
                categories.add(course['category'].lower())
            if course['tags']:
                all_tags.update(t.lower() for t in course['tags'] if isinstance(t, str))
            if course['difficulty_level']:
                difficulty_levels.add(course['difficulty_level'].lower())
        
        # Build feature index
        self._feature_names = []
        feature_index = {}
        
        # Category features
        for cat in sorted(categories):
            feature_index[f'cat_{cat}'] = len(self._feature_names)
            self._feature_names.append(f'cat_{cat}')
        
        # Tag features
        for tag in sorted(all_tags):
            feature_index[f'tag_{tag}'] = len(self._feature_names)
            self._feature_names.append(f'tag_{tag}')
        
        # Difficulty features
        for diff in sorted(difficulty_levels):
            feature_index[f'diff_{diff}'] = len(self._feature_names)
            self._feature_names.append(f'diff_{diff}')
        
        # Duration buckets (normalized feature)
        self._feature_names.append('duration_normalized')
        feature_index['duration_normalized'] = len(self._feature_names) - 1
        
        n_features = len(self._feature_names)
        
        # Build feature vectors for each course
        self._course_id_list = []
        feature_vectors = []
        
        # Get max duration for normalization
        max_duration = max((c['estimated_duration'] or 1) for c in courses)
        
        for course in courses:
            course_id = str(course['id'])
            self._course_id_list.append(course_id)
            self._course_metadata[course_id] = course
            
            # Build feature vector
            features = np.zeros(n_features)
            
            # Category feature
            if course['category']:
                cat_key = f"cat_{course['category'].lower()}"
                if cat_key in feature_index:
                    features[feature_index[cat_key]] = 1.0
            
            # Tag features
            if course['tags']:
                for tag in course['tags']:
                    if isinstance(tag, str):
                        tag_key = f"tag_{tag.lower()}"
                        if tag_key in feature_index:
                            features[feature_index[tag_key]] = 1.0
            
            # Difficulty feature
            if course['difficulty_level']:
                diff_key = f"diff_{course['difficulty_level'].lower()}"
                if diff_key in feature_index:
                    features[feature_index[diff_key]] = 1.0
            
            # Duration (normalized)
            duration = course['estimated_duration'] or 1
            features[feature_index['duration_normalized']] = duration / max_duration
            
            feature_vectors.append(features)
            self._course_features[course_id] = features
        
        # Build feature matrix for efficient similarity computation
        self._feature_matrix = np.array(feature_vectors)
        
        self._model_fitted = True
        self._last_fit_time = timezone.now()
        
        logger.info(
            f"Content-based model fitted: {len(courses)} courses, {n_features} features"
        )
    
    def recommend(
        self, 
        user_id: str, 
        n_recommendations: int = 10,
        exclude_enrolled: bool = True
    ) -> list[RecommendationResult]:
        """
        Generate course recommendations based on content similarity.
        
        Args:
            user_id: The user's ID.
            n_recommendations: Number of recommendations to return.
            exclude_enrolled: Whether to exclude courses the user is already enrolled in.
            
        Returns:
            List of RecommendationResult objects.
        """
        from apps.enrollments.models import Enrollment
        
        if not self._model_fitted:
            logger.warning("Model not fitted, cannot generate recommendations")
            return []
        
        # Get user's enrolled courses with high engagement
        enrollments = Enrollment.objects.filter(
            user_id=user_id,
            status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED]
        ).filter(
            Q(progress__gte=30) | Q(status=Enrollment.Status.COMPLETED)
        ).select_related('course').order_by('-progress')[:10]
        
        if not enrollments:
            return self._cold_start_recommendations(user_id, n_recommendations)
        
        # Build user profile as weighted average of engaged course features
        user_profile = np.zeros(len(self._feature_names))
        total_weight = 0
        
        for enrollment in enrollments:
            course_id = str(enrollment.course_id)
            if course_id in self._course_features:
                # Weight by engagement level
                weight = 0.5 + (enrollment.progress / 100) * 0.5
                if enrollment.status == Enrollment.Status.COMPLETED:
                    weight *= 1.2
                
                user_profile += self._course_features[course_id] * weight
                total_weight += weight
        
        if total_weight > 0:
            user_profile /= total_weight
        
        # Calculate similarity with all courses
        user_profile = user_profile.reshape(1, -1)
        similarities = cosine_similarity(user_profile, self._feature_matrix)[0]
        
        # Get enrolled course IDs to exclude
        excluded_items = set()
        if exclude_enrolled:
            enrolled = Enrollment.objects.filter(user_id=user_id).values_list('course_id', flat=True)
            excluded_items = {str(cid) for cid in enrolled}
        
        # Build recommendations
        course_scores = []
        for idx, similarity in enumerate(similarities):
            course_id = self._course_id_list[idx]
            if course_id not in excluded_items:
                course_scores.append((course_id, similarity))
        
        course_scores.sort(key=lambda x: x[1], reverse=True)
        
        recommendations = []
        for course_id, score in course_scores[:n_recommendations]:
            metadata = self._course_metadata.get(course_id, {})
            
            recommendations.append(RecommendationResult(
                item_id=course_id,
                item_type='course',
                title=metadata.get('title', 'Unknown Course'),
                score=float(score),
                reason='Similar to courses you\'ve engaged with',
                metadata={
                    'slug': metadata.get('slug', ''),
                    'description': (metadata.get('description', '') or '')[:200],
                    'category': metadata.get('category', ''),
                    'difficulty_level': metadata.get('difficulty_level', ''),
                    'algorithm': 'content_based'
                }
            ))
        
        return recommendations
    
    def _cold_start_recommendations(
        self, 
        user_id: str, 
        n_recommendations: int
    ) -> list[RecommendationResult]:
        """Generate recommendations for users with no engagement history."""
        # Return courses with diverse categories
        recommendations = []
        seen_categories = set()
        
        for course_id in self._course_id_list:
            metadata = self._course_metadata.get(course_id, {})
            category = metadata.get('category', '')
            
            # Prioritize diversity
            if category not in seen_categories or len(recommendations) < n_recommendations // 2:
                seen_categories.add(category)
                recommendations.append(RecommendationResult(
                    item_id=course_id,
                    item_type='course',
                    title=metadata.get('title', 'Unknown Course'),
                    score=0.5,
                    reason='Explore this category',
                    metadata={
                        'slug': metadata.get('slug', ''),
                        'description': (metadata.get('description', '') or '')[:200],
                        'category': category,
                        'difficulty_level': metadata.get('difficulty_level', ''),
                        'algorithm': 'diversity_fallback'
                    }
                ))
            
            if len(recommendations) >= n_recommendations:
                break
        
        return recommendations
    
    def get_similar_courses(
        self, 
        course_id: str, 
        n_similar: int = 5
    ) -> list[RecommendationResult]:
        """
        Find courses similar to a given course.
        
        Args:
            course_id: The target course's ID.
            n_similar: Number of similar courses to return.
            
        Returns:
            List of RecommendationResult objects.
        """
        if not self._model_fitted:
            return []
        
        course_id_str = str(course_id)
        if course_id_str not in self._course_features:
            return []
        
        course_vector = self._course_features[course_id_str].reshape(1, -1)
        similarities = cosine_similarity(course_vector, self._feature_matrix)[0]
        
        # Get course index
        course_idx = self._course_id_list.index(course_id_str)
        
        # Sort by similarity (excluding self)
        course_scores = [
            (self._course_id_list[i], sim) 
            for i, sim in enumerate(similarities) 
            if i != course_idx
        ]
        course_scores.sort(key=lambda x: x[1], reverse=True)
        
        recommendations = []
        for cid, score in course_scores[:n_similar]:
            metadata = self._course_metadata.get(cid, {})
            recommendations.append(RecommendationResult(
                item_id=cid,
                item_type='course',
                title=metadata.get('title', 'Unknown Course'),
                score=float(score),
                reason='Similar course',
                metadata={
                    'slug': metadata.get('slug', ''),
                    'category': metadata.get('category', ''),
                    'difficulty_level': metadata.get('difficulty_level', ''),
                }
            ))
        
        return recommendations


class HybridRecommender(BaseRecommender):
    """
    Hybrid recommender that combines collaborative and content-based filtering.
    
    Uses weighted combination of both approaches, with automatic weight adjustment
    based on user interaction history.
    """
    
    def __init__(
        self, 
        collaborative_weight: float = 0.6,
        content_weight: float = 0.4,
        min_interactions_for_collaborative: int = 3
    ):
        """
        Initialize the hybrid recommender.
        
        Args:
            collaborative_weight: Weight for collaborative filtering scores.
            content_weight: Weight for content-based filtering scores.
            min_interactions_for_collaborative: Minimum user interactions before 
                collaborative filtering is used.
        """
        super().__init__(min_interactions=1)
        
        self.collaborative_weight = collaborative_weight
        self.content_weight = content_weight
        self.min_interactions_for_collaborative = min_interactions_for_collaborative
        
        # Initialize sub-recommenders
        self._collaborative = CollaborativeRecommender()
        self._content_based = ContentBasedRecommender()
    
    def fit(self, tenant_id: str = None) -> None:
        """
        Train both collaborative and content-based models.
        
        Args:
            tenant_id: Optional tenant ID to filter data by tenant.
        """
        logger.info("Fitting hybrid recommendation model...")
        
        # Fit both sub-models
        self._collaborative.fit(tenant_id)
        self._content_based.fit(tenant_id)
        
        self._model_fitted = (
            self._collaborative._model_fitted or 
            self._content_based._model_fitted
        )
        self._last_fit_time = timezone.now()
        
        logger.info(
            f"Hybrid model fitted: collaborative={self._collaborative._model_fitted}, "
            f"content_based={self._content_based._model_fitted}"
        )
    
    def recommend(
        self, 
        user_id: str, 
        n_recommendations: int = 10,
        exclude_enrolled: bool = True
    ) -> list[RecommendationResult]:
        """
        Generate hybrid recommendations combining both approaches.
        
        Args:
            user_id: The user's ID.
            n_recommendations: Number of recommendations to return.
            exclude_enrolled: Whether to exclude courses the user is already enrolled in.
            
        Returns:
            List of RecommendationResult objects.
        """
        from apps.enrollments.models import Enrollment
        
        if not self._model_fitted:
            logger.warning("Model not fitted, cannot generate recommendations")
            return []
        
        # Get user's interaction count
        user_interactions = Enrollment.objects.filter(user_id=user_id).count()
        
        # Adjust weights based on user interaction history
        # New users get more content-based, established users get more collaborative
        if user_interactions < self.min_interactions_for_collaborative:
            # Cold-start: rely more on content-based
            collab_weight = 0.2
            content_weight = 0.8
        else:
            collab_weight = self.collaborative_weight
            content_weight = self.content_weight
        
        # Get recommendations from both models
        # Request more than needed to allow for merging
        n_request = n_recommendations * 2
        
        collab_recs = []
        content_recs = []
        
        if self._collaborative._model_fitted:
            collab_recs = self._collaborative.recommend(
                user_id, n_request, exclude_enrolled
            )
        
        if self._content_based._model_fitted:
            content_recs = self._content_based.recommend(
                user_id, n_request, exclude_enrolled
            )
        
        # Merge and re-score recommendations
        combined_scores = defaultdict(lambda: {'score': 0.0, 'rec': None, 'sources': []})
        
        for rec in collab_recs:
            key = rec.item_id
            combined_scores[key]['score'] += rec.score * collab_weight
            combined_scores[key]['sources'].append('collaborative')
            if combined_scores[key]['rec'] is None:
                combined_scores[key]['rec'] = rec
        
        for rec in content_recs:
            key = rec.item_id
            combined_scores[key]['score'] += rec.score * content_weight
            combined_scores[key]['sources'].append('content_based')
            if combined_scores[key]['rec'] is None:
                combined_scores[key]['rec'] = rec
        
        # Sort by combined score
        sorted_items = sorted(
            combined_scores.items(), 
            key=lambda x: x[1]['score'], 
            reverse=True
        )
        
        # Build final recommendations
        recommendations = []
        for item_id, data in sorted_items[:n_recommendations]:
            rec = data['rec']
            sources = data['sources']
            
            # Update reason based on sources
            if len(sources) == 2:
                reason = 'Highly recommended based on your interests and similar learners'
            elif 'collaborative' in sources:
                reason = 'Recommended based on learners with similar interests'
            else:
                reason = 'Similar to courses you\'ve engaged with'
            
            recommendations.append(RecommendationResult(
                item_id=rec.item_id,
                item_type=rec.item_type,
                title=rec.title,
                score=data['score'],
                reason=reason,
                metadata={
                    **rec.metadata,
                    'algorithm': 'hybrid',
                    'sources': sources
                }
            ))
        
        return recommendations
    
    def get_explanation(self, user_id: str, course_id: str) -> dict:
        """
        Explain why a course was recommended to a user.
        
        Args:
            user_id: The user's ID.
            course_id: The recommended course's ID.
            
        Returns:
            Dictionary with explanation details.
        """
        from apps.enrollments.models import Enrollment
        
        explanation = {
            'course_id': course_id,
            'user_id': user_id,
            'factors': []
        }
        
        # Check collaborative filtering factors
        if self._collaborative._model_fitted:
            similar_users = self._collaborative.get_similar_users(user_id, 5)
            if similar_users:
                # Check if similar users enrolled in this course
                similar_user_ids = [uid for uid, _ in similar_users]
                similar_enrolled = Enrollment.objects.filter(
                    user_id__in=similar_user_ids,
                    course_id=course_id
                ).count()
                
                if similar_enrolled > 0:
                    explanation['factors'].append({
                        'type': 'collaborative',
                        'description': f'{similar_enrolled} learners with similar interests enrolled in this course',
                        'weight': self.collaborative_weight
                    })
        
        # Check content-based factors
        if self._content_based._model_fitted:
            # Get user's engaged courses
            engaged_courses = Enrollment.objects.filter(
                user_id=user_id,
                progress__gte=50
            ).values_list('course_id', flat=True)[:5]
            
            if engaged_courses:
                similar = self._content_based.get_similar_courses(course_id, 10)
                matching = [r for r in similar if r.item_id in [str(c) for c in engaged_courses]]
                
                if matching:
                    explanation['factors'].append({
                        'type': 'content_based',
                        'description': f'Similar to {len(matching)} course(s) you\'ve engaged with',
                        'similar_courses': [r.title for r in matching[:3]],
                        'weight': self.content_weight
                    })
        
        return explanation


class RiskPredictor:
    """
    ML-based predictor for identifying at-risk students.
    
    Uses engagement patterns, assessment performance, and temporal features
    to predict students who may be at risk of dropping out or failing.
    """
    
    def __init__(self, risk_threshold: float = 0.6):
        """
        Initialize the risk predictor.
        
        Args:
            risk_threshold: Threshold above which a student is considered at-risk.
        """
        self.risk_threshold = risk_threshold
        self._model_fitted = False
        self._feature_weights = None
        self._scaler = MinMaxScaler()
    
    def fit(self, tenant_id: str = None) -> None:
        """
        Train the risk prediction model on historical data.
        
        This uses a rule-based approach with learned weights from historical patterns.
        A more sophisticated implementation could use logistic regression or 
        gradient boosting.
        
        Args:
            tenant_id: Optional tenant ID to filter data by tenant.
        """
        from apps.enrollments.models import Enrollment
        from apps.assessments.models import AssessmentAttempt
        
        logger.info("Fitting risk prediction model...")
        
        # Define feature weights based on domain knowledge
        # These could be learned from labeled historical data
        self._feature_weights = {
            'days_since_last_activity': 0.25,  # Higher = more risk
            'assessment_fail_rate': 0.25,  # Higher = more risk
            'progress_velocity': -0.20,  # Higher = less risk (negative weight)
            'engagement_score': -0.15,  # Higher = less risk
            'time_in_course': -0.10,  # Longer enrollment = less risk (up to a point)
            'content_completion_rate': -0.05,  # Higher = less risk
        }
        
        self._model_fitted = True
        logger.info("Risk prediction model fitted with rule-based weights")
    
    def predict_risk(self, user_id: str, course_id: str = None) -> dict:
        """
        Predict the risk level for a user (optionally for a specific course).
        
        Args:
            user_id: The user's ID.
            course_id: Optional specific course to assess risk for.
            
        Returns:
            Dictionary with risk score, level, and contributing factors.
        """
        from apps.enrollments.models import Enrollment, LearnerProgress
        from apps.assessments.models import AssessmentAttempt
        from django.utils import timezone
        from datetime import timedelta
        
        if not self._model_fitted:
            logger.warning("Model not fitted, using default risk assessment")
            return {'risk_score': 0.5, 'risk_level': 'medium', 'factors': []}
        
        # Get enrollment data
        enrollment_query = Enrollment.objects.filter(
            user_id=user_id,
            status=Enrollment.Status.ACTIVE
        )
        
        if course_id:
            enrollment_query = enrollment_query.filter(course_id=course_id)
        
        enrollments = list(enrollment_query.select_related('course'))
        
        if not enrollments:
            return {
                'risk_score': 0.0,
                'risk_level': 'none',
                'factors': [],
                'message': 'No active enrollments found'
            }
        
        # Calculate features for each enrollment and aggregate
        risk_scores = []
        all_factors = []
        
        for enrollment in enrollments:
            features, factors = self._calculate_features(enrollment)
            risk_score = self._calculate_risk_score(features)
            risk_scores.append(risk_score)
            all_factors.extend(factors)
        
        # Aggregate risk score
        avg_risk = np.mean(risk_scores)
        
        # Determine risk level
        if avg_risk >= 0.7:
            risk_level = 'high'
        elif avg_risk >= 0.4:
            risk_level = 'medium'
        else:
            risk_level = 'low'
        
        # Deduplicate and prioritize factors
        unique_factors = []
        seen = set()
        for factor in sorted(all_factors, key=lambda x: x['impact'], reverse=True):
            if factor['type'] not in seen:
                unique_factors.append(factor)
                seen.add(factor['type'])
        
        return {
            'risk_score': round(avg_risk, 3),
            'risk_level': risk_level,
            'factors': unique_factors[:5],  # Top 5 factors
            'enrollments_analyzed': len(enrollments),
            'recommendations': self._get_risk_recommendations(risk_level, unique_factors)
        }
    
    def _calculate_features(self, enrollment) -> tuple[dict, list]:
        """Calculate risk features for an enrollment."""
        from apps.enrollments.models import LearnerProgress
        from apps.assessments.models import AssessmentAttempt
        from django.utils import timezone
        from datetime import timedelta
        
        features = {}
        factors = []
        now = timezone.now()
        
        # Feature 1: Days since last activity
        progress_items = LearnerProgress.objects.filter(
            enrollment=enrollment
        ).order_by('-updated_at').first()
        
        if progress_items:
            last_activity = progress_items.updated_at
        else:
            last_activity = enrollment.enrolled_at
        
        days_inactive = (now - last_activity).days
        features['days_since_last_activity'] = min(days_inactive / 30, 1.0)  # Normalize to 30 days
        
        if days_inactive > 7:
            factors.append({
                'type': 'inactivity',
                'description': f'No activity in {days_inactive} days',
                'impact': min(days_inactive / 30, 1.0)
            })
        
        # Feature 2: Assessment fail rate
        attempts = AssessmentAttempt.objects.filter(
            user_id=enrollment.user_id,
            assessment__course_id=enrollment.course_id,
            status=AssessmentAttempt.AttemptStatus.GRADED
        )
        
        total_attempts = attempts.count()
        if total_attempts > 0:
            failed_attempts = attempts.filter(is_passed=False).count()
            fail_rate = failed_attempts / total_attempts
            features['assessment_fail_rate'] = fail_rate
            
            if fail_rate > 0.5:
                factors.append({
                    'type': 'assessment_performance',
                    'description': f'Failed {failed_attempts}/{total_attempts} assessments',
                    'impact': fail_rate
                })
        else:
            features['assessment_fail_rate'] = 0.0
        
        # Feature 3: Progress velocity (progress per day enrolled)
        days_enrolled = max((now - enrollment.enrolled_at).days, 1)
        progress_per_day = enrollment.progress / days_enrolled
        features['progress_velocity'] = min(progress_per_day / 5, 1.0)  # Normalize to 5% per day
        
        if progress_per_day < 1 and days_enrolled > 7:
            factors.append({
                'type': 'slow_progress',
                'description': f'Progress rate: {progress_per_day:.1f}% per day',
                'impact': max(0, 1 - progress_per_day / 2)
            })
        
        # Feature 4: Engagement score (based on content interactions)
        total_content = LearnerProgress.objects.filter(enrollment=enrollment).count()
        completed_content = LearnerProgress.objects.filter(
            enrollment=enrollment,
            status=LearnerProgress.Status.COMPLETED
        ).count()
        
        if total_content > 0:
            engagement = completed_content / total_content
        else:
            engagement = 0.0
        
        features['engagement_score'] = engagement
        features['content_completion_rate'] = engagement
        
        if engagement < 0.3 and days_enrolled > 14:
            factors.append({
                'type': 'low_engagement',
                'description': f'Only {completed_content}/{total_content} content items completed',
                'impact': 1 - engagement
            })
        
        # Feature 5: Time in course (normalized)
        expected_duration_days = (enrollment.course.estimated_duration or 10) * 7  # hours -> days estimate
        time_ratio = days_enrolled / expected_duration_days
        features['time_in_course'] = min(time_ratio, 2.0) / 2.0  # Normalize
        
        if time_ratio > 1.5 and enrollment.progress < 80:
            factors.append({
                'type': 'behind_schedule',
                'description': 'Significantly behind expected timeline',
                'impact': min(time_ratio - 1, 1.0)
            })
        
        return features, factors
    
    def _calculate_risk_score(self, features: dict) -> float:
        """Calculate weighted risk score from features."""
        score = 0.5  # Base risk
        
        for feature_name, value in features.items():
            if feature_name in self._feature_weights:
                weight = self._feature_weights[feature_name]
                score += weight * value
        
        # Clamp to [0, 1]
        return max(0.0, min(1.0, score))
    
    def _get_risk_recommendations(self, risk_level: str, factors: list) -> list:
        """Generate recommendations based on risk level and factors."""
        recommendations = []
        
        factor_types = {f['type'] for f in factors}
        
        if 'inactivity' in factor_types:
            recommendations.append({
                'action': 'send_reminder',
                'description': 'Send a personalized reminder to re-engage with the course',
                'priority': 'high'
            })
        
        if 'assessment_performance' in factor_types:
            recommendations.append({
                'action': 'provide_support',
                'description': 'Offer additional study resources or tutoring support',
                'priority': 'high'
            })
        
        if 'slow_progress' in factor_types:
            recommendations.append({
                'action': 'adjust_pace',
                'description': 'Suggest a revised learning schedule',
                'priority': 'medium'
            })
        
        if 'low_engagement' in factor_types:
            recommendations.append({
                'action': 'personalize_content',
                'description': 'Recommend specific content items based on interests',
                'priority': 'medium'
            })
        
        if risk_level == 'high':
            recommendations.append({
                'action': 'instructor_outreach',
                'description': 'Flag for instructor or mentor intervention',
                'priority': 'high'
            })
        
        return recommendations
    
    def get_at_risk_students(
        self, 
        course_id: str = None, 
        tenant_id: str = None,
        limit: int = 50
    ) -> list[dict]:
        """
        Get a list of at-risk students for a course or tenant.
        
        Args:
            course_id: Optional course ID to filter by.
            tenant_id: Optional tenant ID to filter by.
            limit: Maximum number of students to return.
            
        Returns:
            List of at-risk student assessments, sorted by risk level.
        """
        from apps.enrollments.models import Enrollment
        
        enrollment_query = Enrollment.objects.filter(
            status=Enrollment.Status.ACTIVE
        ).select_related('user', 'course')
        
        if course_id:
            enrollment_query = enrollment_query.filter(course_id=course_id)
        
        if tenant_id:
            enrollment_query = enrollment_query.filter(course__tenant_id=tenant_id)
        
        # Get unique users
        user_courses = {}
        for enrollment in enrollment_query[:500]:  # Limit for performance
            key = str(enrollment.user_id)
            if key not in user_courses:
                user_courses[key] = []
            user_courses[key].append(enrollment)
        
        # Assess risk for each user
        at_risk = []
        
        for user_id, enrollments in user_courses.items():
            risk_data = self.predict_risk(user_id, course_id)
            
            if risk_data['risk_score'] >= self.risk_threshold:
                user = enrollments[0].user
                at_risk.append({
                    'user_id': user_id,
                    'user_email': user.email,
                    'user_name': f'{user.first_name} {user.last_name}'.strip() or user.email,
                    'risk_score': risk_data['risk_score'],
                    'risk_level': risk_data['risk_level'],
                    'factors': risk_data['factors'],
                    'recommendations': risk_data['recommendations'],
                    'courses': [
                        {
                            'id': str(e.course_id),
                            'title': e.course.title,
                            'progress': e.progress
                        }
                        for e in enrollments
                    ]
                })
        
        # Sort by risk score (highest first)
        at_risk.sort(key=lambda x: x['risk_score'], reverse=True)
        
        return at_risk[:limit]


class ModuleRecommender:
    """
    Module-level recommender that uses skill gap analysis, prerequisites, and
    collaborative filtering to recommend the best modules for a learner.
    
    This recommender combines:
    1. Skill gap analysis: Recommends modules that teach skills the user needs
    2. Prerequisite checking: Filters out modules where prerequisites aren't met
    3. Collaborative filtering: Considers what similar learners completed
    4. Learning style preferences: Adjusts recommendations based on user preferences
    """
    
    def __init__(
        self,
        user,
        target_skills: list[str] = None,
        skill_weight: float = 0.5,
        collaborative_weight: float = 0.3,
        popularity_weight: float = 0.2
    ):
        """
        Initialize the module recommender for a specific user.
        
        Args:
            user: The User object to generate recommendations for
            target_skills: Optional list of skill IDs to focus recommendations on
            skill_weight: Weight for skill-based scoring (default 0.5)
            collaborative_weight: Weight for collaborative filtering (default 0.3)
            popularity_weight: Weight for popularity-based scoring (default 0.2)
        """
        self.user = user
        self.target_skills = target_skills or []
        self.skill_weight = skill_weight
        self.collaborative_weight = collaborative_weight
        self.popularity_weight = popularity_weight
        
        # Caches
        self._user_skill_progress = None
        self._completed_modules = None
        self._similar_users = None
    
    def get_recommendations(
        self,
        limit: int = 10,
        course_id: str = None,
        exclude_completed: bool = True,
        check_prerequisites: bool = True
    ) -> list[RecommendationResult]:
        """
        Generate module recommendations for the user.
        
        Args:
            limit: Maximum number of recommendations to return
            course_id: Optional course ID to filter modules from
            exclude_completed: Whether to exclude completed modules
            check_prerequisites: Whether to filter by prerequisite requirements
            
        Returns:
            List of RecommendationResult objects sorted by relevance
        """
        from django.db.models import Q
        from apps.courses.models import Module
        from apps.enrollments.models import Enrollment, LearnerProgress
        
        logger.info(f"Generating module recommendations for user {self.user.id}")
        
        # Get candidate modules - scope to user's tenant
        module_query = Module.objects.filter(
            course__status='PUBLISHED',
            course__tenant=self.user.tenant
        ).select_related('course').prefetch_related('skill_mappings__skill')
        
        if course_id:
            module_query = module_query.filter(course_id=course_id)
        else:
            # Filter to modules in courses the user has access to (enrolled or free)
            enrolled_courses = Enrollment.objects.filter(
                user=self.user,
                status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED]
            ).values_list('course_id', flat=True)
            
            module_query = module_query.filter(
                Q(course_id__in=enrolled_courses) | Q(course__is_free=True)
            )
        
        # Exclude completed modules if requested
        if exclude_completed:
            completed_content = LearnerProgress.objects.filter(
                enrollment__user=self.user,
                status=LearnerProgress.Status.COMPLETED
            ).values_list('content_item__module_id', flat=True).distinct()
            
            # Get modules where all required content is completed
            self._completed_modules = self._get_completed_modules()
            module_query = module_query.exclude(id__in=self._completed_modules)
        
        # Filter by prerequisites if requested
        if check_prerequisites:
            module_query = self._filter_by_prerequisites(module_query)
        
        modules = list(module_query[:100])  # Limit candidates for performance
        
        if not modules:
            logger.info("No candidate modules found")
            return []
        
        # Score and rank modules
        scored_modules = []
        for module in modules:
            score, reason = self.score_module(module)
            if score > 0:
                scored_modules.append((module, score, reason))
        
        # Sort by score (descending)
        scored_modules.sort(key=lambda x: x[1], reverse=True)
        
        # Build recommendation results
        recommendations = []
        for module, score, reason in scored_modules[:limit]:
            recommendations.append(RecommendationResult(
                item_id=str(module.id),
                item_type='module',
                title=module.title,
                score=score,
                reason=reason,
                metadata={
                    'course_id': str(module.course_id),
                    'course_title': module.course.title,
                    'course_slug': module.course.slug,
                    'module_order': module.order,
                    'description': (module.description or '')[:200],
                    'skills': [
                        {
                            'id': str(ms.skill_id),
                            'name': ms.skill.name,
                            'contribution': ms.contribution_level,
                            'proficiency_gained': ms.proficiency_gained
                        }
                        for ms in module.skill_mappings.all()[:5]
                    ],
                    'algorithm': 'module_recommender'
                }
            ))
        
        return recommendations
    
    def score_module(self, module) -> tuple[float, str]:
        """
        Calculate a relevance score for a module.
        
        Combines:
        - Skill gap score: How well the module addresses user's skill gaps
        - Collaborative score: How popular with similar users
        - Popularity score: General popularity
        
        Args:
            module: Module object to score
            
        Returns:
            Tuple of (score 0-1, reason string)
        """
        from apps.skills.models import ModuleSkill, LearnerSkillProgress
        
        skill_score = 0.0
        collaborative_score = 0.0
        popularity_score = 0.0
        primary_reason = "Recommended module"
        
        # 1. Skill gap score
        skill_score, skill_reason = self._calculate_skill_score(module)
        if skill_reason:
            primary_reason = skill_reason
        
        # 2. Collaborative filtering score
        collaborative_score, collab_reason = self._calculate_collaborative_score(module)
        if collab_reason and not skill_reason:
            primary_reason = collab_reason
        
        # 3. Popularity score
        popularity_score = self._calculate_popularity_score(module)
        
        # Combine scores with weights
        total_score = (
            self.skill_weight * skill_score +
            self.collaborative_weight * collaborative_score +
            self.popularity_weight * popularity_score
        )
        
        # Normalize to 0-1
        total_score = min(1.0, max(0.0, total_score))
        
        return (total_score, primary_reason)
    
    def _calculate_skill_score(self, module) -> tuple[float, str]:
        """
        Calculate how well a module addresses user's skill gaps.
        
        Higher score for modules that:
        - Teach skills where user has low proficiency
        - Match user's target skills (if specified)
        - Have high proficiency_gained values
        """
        from apps.skills.models import ModuleSkill, LearnerSkillProgress
        
        if self._user_skill_progress is None:
            self._user_skill_progress = {
                str(sp.skill_id): sp.proficiency_score
                for sp in LearnerSkillProgress.objects.filter(user=self.user)
            }
        
        module_skills = list(module.skill_mappings.all())
        
        if not module_skills:
            return (0.0, "")
        
        total_gap_score = 0.0
        max_gap_skill = None
        max_gap = 0
        
        for ms in module_skills:
            skill_id = str(ms.skill_id)
            current_proficiency = self._user_skill_progress.get(skill_id, 0)
            
            # Calculate skill gap (how much room for improvement)
            # Higher gap = more value from this module
            gap = 100 - current_proficiency
            
            # Weight by how much proficiency this module provides
            potential_gain = min(ms.proficiency_gained, gap)
            
            # Boost if this is a target skill
            target_boost = 1.5 if skill_id in self.target_skills else 1.0
            
            # Boost for primary skills
            primary_boost = 1.2 if ms.is_primary else 1.0
            
            # Contribution level weights
            contribution_weights = {
                'INTRODUCES': 0.8,
                'DEVELOPS': 1.0,
                'REINFORCES': 0.9,
                'MASTERS': 1.1
            }
            contribution_weight = contribution_weights.get(ms.contribution_level, 1.0)
            
            skill_value = (potential_gain / 100) * target_boost * primary_boost * contribution_weight
            total_gap_score += skill_value
            
            if gap > max_gap:
                max_gap = gap
                max_gap_skill = ms.skill
        
        # Normalize score
        avg_score = total_gap_score / len(module_skills) if module_skills else 0
        
        # Generate reason
        reason = ""
        if max_gap_skill and max_gap > 30:
            reason = f"Builds your {max_gap_skill.name} skills"
        elif module_skills:
            reason = f"Develops {len(module_skills)} skills"
        
        return (min(1.0, avg_score), reason)
    
    def _calculate_collaborative_score(self, module) -> tuple[float, str]:
        """
        Calculate score based on what similar users completed.
        
        Uses collaborative filtering to find users with similar skill profiles
        and sees which modules they completed successfully.
        """
        from apps.enrollments.models import Enrollment, LearnerProgress
        from apps.skills.models import LearnerSkillProgress
        
        # Find similar users if not cached
        if self._similar_users is None:
            self._similar_users = self._find_similar_users()
        
        if not self._similar_users:
            return (0.0, "")
        
        similar_user_ids = [uid for uid, _ in self._similar_users[:20]]
        
        # Count how many similar users completed this module's content
        completions = LearnerProgress.objects.filter(
            enrollment__user_id__in=similar_user_ids,
            content_item__module=module,
            status=LearnerProgress.Status.COMPLETED
        ).values('enrollment__user_id').distinct().count()
        
        # Calculate score based on completion rate
        if similar_user_ids:
            completion_rate = completions / len(similar_user_ids)
        else:
            completion_rate = 0
        
        reason = ""
        if completion_rate > 0.3:
            reason = "Popular with learners like you"
        
        return (completion_rate, reason)
    
    def _calculate_popularity_score(self, module) -> float:
        """
        Calculate general popularity score for a module.
        
        Based on overall completion rates and ratings.
        """
        from apps.enrollments.models import LearnerProgress
        from django.db.models import Count
        
        # Count total completions for this module
        total_completions = LearnerProgress.objects.filter(
            content_item__module=module,
            status=LearnerProgress.Status.COMPLETED
        ).values('enrollment__user_id').distinct().count()
        
        # Normalize based on typical completion counts
        # Using a sigmoid-like function to cap at 1.0
        normalized = min(1.0, total_completions / 100)
        
        return normalized
    
    def _find_similar_users(self, n_similar: int = 50) -> list[tuple[str, float]]:
        """
        Find users with similar skill profiles.
        
        Uses cosine similarity on skill proficiency vectors.
        
        Args:
            n_similar: Number of similar users to find
            
        Returns:
            List of (user_id, similarity_score) tuples
        """
        from apps.skills.models import LearnerSkillProgress
        
        # Get all users with skill progress in the same tenant
        if not hasattr(self.user, 'tenant_id') or not self.user.tenant_id:
            # Fallback: get all users with skill progress
            all_progress = LearnerSkillProgress.objects.all()
        else:
            all_progress = LearnerSkillProgress.objects.filter(
                skill__tenant_id=self.user.tenant_id
            )
        
        # Build skill vectors for all users
        user_skills = {}
        skill_ids = set()
        
        for progress in all_progress.values('user_id', 'skill_id', 'proficiency_score'):
            user_id = str(progress['user_id'])
            skill_id = str(progress['skill_id'])
            score = progress['proficiency_score']
            
            if user_id not in user_skills:
                user_skills[user_id] = {}
            user_skills[user_id][skill_id] = score
            skill_ids.add(skill_id)
        
        if not skill_ids or str(self.user.id) not in user_skills:
            return []
        
        # Build vectors
        skill_list = sorted(skill_ids)
        current_user_id = str(self.user.id)
        current_user_vector = np.array([
            user_skills.get(current_user_id, {}).get(sid, 0)
            for sid in skill_list
        ])
        
        # Calculate similarity with all other users
        similarities = []
        for user_id, skills in user_skills.items():
            if user_id == current_user_id:
                continue
            
            other_vector = np.array([skills.get(sid, 0) for sid in skill_list])
            
            # Cosine similarity
            norm_current = np.linalg.norm(current_user_vector)
            norm_other = np.linalg.norm(other_vector)
            
            if norm_current > 0 and norm_other > 0:
                similarity = np.dot(current_user_vector, other_vector) / (norm_current * norm_other)
                similarities.append((user_id, float(similarity)))
        
        # Sort by similarity and return top N
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:n_similar]
    
    def _get_completed_modules(self) -> set:
        """
        Get set of module IDs where user has completed all required content.
        """
        from apps.courses.models import Module, ContentItem
        from apps.enrollments.models import LearnerProgress
        from django.db.models import Count, Q
        
        # Get modules the user is enrolled in
        from apps.enrollments.models import Enrollment
        enrolled_courses = Enrollment.objects.filter(
            user=self.user,
            status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED]
        ).values_list('course_id', flat=True)
        
        completed_modules = set()
        
        # For each module, check if all required content is completed
        modules = Module.objects.filter(course_id__in=enrolled_courses)
        
        for module in modules:
            required_items = ContentItem.objects.filter(
                module=module,
                is_required=True,
                is_published=True
            ).count()
            
            if required_items == 0:
                # No required items = not completed (module hasn't had content added yet)
                # Only consider a module completed if it has content AND user finished it
                continue
            
            completed_items = LearnerProgress.objects.filter(
                enrollment__user=self.user,
                enrollment__course=module.course,
                content_item__module=module,
                content_item__is_required=True,
                content_item__is_published=True,
                status=LearnerProgress.Status.COMPLETED
            ).count()
            
            if completed_items >= required_items:
                completed_modules.add(module.id)
        
        return completed_modules
    
    def _filter_by_prerequisites(self, module_query):
        """
        Filter module queryset to only include modules where prerequisites are met.
        
        Args:
            module_query: QuerySet of modules
            
        Returns:
            Filtered QuerySet
        """
        from apps.courses.models import ModulePrerequisite
        
        # Get all modules with their prerequisite status
        valid_module_ids = []
        
        for module in module_query:
            prereqs_met, _ = module.are_prerequisites_met(self.user, check_type='REQUIRED')
            if prereqs_met:
                valid_module_ids.append(module.id)
        
        return module_query.filter(id__in=valid_module_ids)
    
    def get_skill_gap_analysis(self, target_skills: list[str] = None) -> list[dict]:
        """
        Analyze skill gaps and recommend modules to fill them.
        
        Args:
            target_skills: Optional list of skill IDs to analyze
            
        Returns:
            List of skill gap analyses with recommended modules
        """
        from apps.skills.models import Skill, ModuleSkill, LearnerSkillProgress
        
        skills_to_analyze = target_skills or self.target_skills
        
        if not skills_to_analyze:
            # Get all skills the user has some progress on or should develop
            skills_to_analyze = list(
                LearnerSkillProgress.objects.filter(user=self.user)
                .values_list('skill_id', flat=True)
            )
        
        gaps = []
        
        for skill_id in skills_to_analyze:
            try:
                skill = Skill.objects.get(id=skill_id)
            except Skill.DoesNotExist:
                continue
            
            # Get user's current proficiency
            try:
                progress = LearnerSkillProgress.objects.get(user=self.user, skill=skill)
                current_proficiency = progress.proficiency_score
                current_level = progress.proficiency_level
            except LearnerSkillProgress.DoesNotExist:
                current_proficiency = 0
                current_level = Skill.ProficiencyLevel.NOVICE
            
            # Find modules that teach this skill
            module_skills = ModuleSkill.objects.filter(
                skill=skill
            ).select_related('module', 'module__course').order_by(
                '-proficiency_gained', 'module__order'
            )[:5]
            
            recommended_modules = [
                {
                    'module_id': str(ms.module_id),
                    'module_title': ms.module.title,
                    'course_id': str(ms.module.course_id),
                    'course_title': ms.module.course.title,
                    'contribution_level': ms.contribution_level,
                    'proficiency_gained': ms.proficiency_gained
                }
                for ms in module_skills
            ]
            
            gaps.append({
                'skill_id': str(skill.id),
                'skill_name': skill.name,
                'category': skill.category,
                'current_proficiency': current_proficiency,
                'current_level': current_level,
                'gap': 100 - current_proficiency,
                'recommended_modules': recommended_modules
            })
        
        # Sort by gap size (largest gaps first)
        gaps.sort(key=lambda x: x['gap'], reverse=True)
        
        return gaps


# Singleton instances for use across the application
_collaborative_recommender = None
_content_based_recommender = None
_hybrid_recommender = None
_risk_predictor = None


def get_collaborative_recommender() -> CollaborativeRecommender:
    """Get or create the singleton collaborative recommender instance."""
    global _collaborative_recommender
    if _collaborative_recommender is None:
        _collaborative_recommender = CollaborativeRecommender()
    return _collaborative_recommender


def get_content_based_recommender() -> ContentBasedRecommender:
    """Get or create the singleton content-based recommender instance."""
    global _content_based_recommender
    if _content_based_recommender is None:
        _content_based_recommender = ContentBasedRecommender()
    return _content_based_recommender


def get_hybrid_recommender() -> HybridRecommender:
    """Get or create the singleton hybrid recommender instance."""
    global _hybrid_recommender
    if _hybrid_recommender is None:
        _hybrid_recommender = HybridRecommender()
    return _hybrid_recommender


def get_risk_predictor() -> RiskPredictor:
    """Get or create the singleton risk predictor instance."""
    global _risk_predictor
    if _risk_predictor is None:
        _risk_predictor = RiskPredictor()
    return _risk_predictor
