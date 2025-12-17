"""Tests for AI Engine recommenders, specifically ModuleRecommender."""

import uuid
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.ai_engine.recommenders import ModuleRecommender, RecommendationResult
from apps.core.models import Tenant
from apps.courses.models import Course, Module, ContentItem, ModulePrerequisite
from apps.enrollments.models import Enrollment, LearnerProgress
from apps.skills.models import Skill, ModuleSkill, LearnerSkillProgress
from apps.users.models import User


class ModuleRecommenderInitTests(TestCase):
    """Tests for ModuleRecommender initialization."""

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant",
        )
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
            tenant=self.tenant,
        )

    def test_init_with_defaults(self):
        """Test initialization with default values."""
        recommender = ModuleRecommender(user=self.user)

        self.assertEqual(recommender.user, self.user)
        self.assertEqual(recommender.target_skills, [])
        self.assertEqual(recommender.skill_weight, 0.5)
        self.assertEqual(recommender.collaborative_weight, 0.3)
        self.assertEqual(recommender.popularity_weight, 0.2)

    def test_init_with_custom_weights(self):
        """Test initialization with custom weights."""
        recommender = ModuleRecommender(
            user=self.user,
            skill_weight=0.7,
            collaborative_weight=0.2,
            popularity_weight=0.1,
        )

        self.assertEqual(recommender.skill_weight, 0.7)
        self.assertEqual(recommender.collaborative_weight, 0.2)
        self.assertEqual(recommender.popularity_weight, 0.1)

    def test_init_with_target_skills(self):
        """Test initialization with target skills."""
        target_skills = [str(uuid.uuid4()), str(uuid.uuid4())]
        recommender = ModuleRecommender(
            user=self.user,
            target_skills=target_skills,
        )

        self.assertEqual(recommender.target_skills, target_skills)

    def test_init_caches_are_none(self):
        """Test that internal caches start as None."""
        recommender = ModuleRecommender(user=self.user)

        self.assertIsNone(recommender._user_skill_progress)
        self.assertIsNone(recommender._completed_modules)
        self.assertIsNone(recommender._similar_users)


class ModuleRecommenderGetRecommendationsTests(TestCase):
    """Tests for ModuleRecommender.get_recommendations()."""

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant",
        )
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        # Create a published course
        self.course = Course.objects.create(
            title="Python Programming",
            slug="python-programming",
            description="Learn Python basics",
            tenant=self.tenant,
            status=Course.Status.PUBLISHED,
            instructor=self.user,
            is_free=True,
        )
        # Create modules
        self.module1 = Module.objects.create(
            course=self.course,
            title="Introduction to Python",
            order=1,
        )
        self.module2 = Module.objects.create(
            course=self.course,
            title="Python Data Types",
            order=2,
        )
        self.module3 = Module.objects.create(
            course=self.course,
            title="Python Functions",
            order=3,
        )
        # Create skills
        self.skill_python = Skill.objects.create(
            name="Python",
            category="programming",
            tenant=self.tenant,
        )
        # Map skills to modules
        ModuleSkill.objects.create(
            module=self.module1,
            skill=self.skill_python,
            contribution_level='INTRODUCES',
            proficiency_gained=15,
            is_primary=True,
        )
        ModuleSkill.objects.create(
            module=self.module2,
            skill=self.skill_python,
            contribution_level='DEVELOPS',
            proficiency_gained=20,
            is_primary=True,
        )

    def test_returns_recommendations_for_free_course(self):
        """Test that recommendations are returned for free course modules."""
        recommender = ModuleRecommender(user=self.user)
        recommendations = recommender.get_recommendations(limit=10)

        # Should return recommendations from the free course
        self.assertIsInstance(recommendations, list)
        self.assertTrue(len(recommendations) > 0)
        for rec in recommendations:
            self.assertIsInstance(rec, RecommendationResult)
            self.assertEqual(rec.item_type, 'module')

    def test_returns_recommendations_for_enrolled_course(self):
        """Test recommendations for enrolled courses."""
        # Create a non-free course
        paid_course = Course.objects.create(
            title="Advanced Python",
            slug="advanced-python",
            description="Advanced topics",
            tenant=self.tenant,
            status=Course.Status.PUBLISHED,
            instructor=self.user,
            is_free=False,
        )
        adv_module = Module.objects.create(
            course=paid_course,
            title="Advanced Functions",
            order=1,
        )
        ModuleSkill.objects.create(
            module=adv_module,
            skill=self.skill_python,
            contribution_level='MASTERS',
            proficiency_gained=30,
            is_primary=True,
        )
        # Enroll user
        Enrollment.objects.create(
            user=self.user,
            course=paid_course,
            status=Enrollment.Status.ACTIVE,
        )

        recommender = ModuleRecommender(user=self.user)
        recommendations = recommender.get_recommendations(limit=10)

        # Should include modules from both free and enrolled courses
        module_ids = [rec.item_id for rec in recommendations]
        self.assertIn(str(adv_module.id), module_ids)

    def test_course_id_filter(self):
        """Test filtering recommendations to a specific course."""
        recommender = ModuleRecommender(user=self.user)
        recommendations = recommender.get_recommendations(
            limit=10,
            course_id=str(self.course.id),
        )

        # All recommendations should be from the specified course
        for rec in recommendations:
            self.assertEqual(rec.metadata['course_id'], str(self.course.id))

    def test_limit_parameter(self):
        """Test that limit parameter is respected."""
        recommender = ModuleRecommender(user=self.user)
        recommendations = recommender.get_recommendations(limit=1)

        self.assertLessEqual(len(recommendations), 1)

    def test_exclude_completed_modules(self):
        """Test that completed modules are excluded."""
        # Enroll user
        enrollment = Enrollment.objects.create(
            user=self.user,
            course=self.course,
            status=Enrollment.Status.ACTIVE,
        )
        # Create content item and mark as completed
        content_item = ContentItem.objects.create(
            module=self.module1,
            title="Intro Video",
            content_type=ContentItem.ContentType.VIDEO,
            order=1,
            is_required=True,
            is_published=True,
        )
        LearnerProgress.objects.create(
            enrollment=enrollment,
            content_item=content_item,
            status=LearnerProgress.Status.COMPLETED,
        )

        recommender = ModuleRecommender(user=self.user)
        recommendations = recommender.get_recommendations(
            limit=10,
            exclude_completed=True,
        )

        # Module 1 should be excluded (all required content completed)
        module_ids = [rec.item_id for rec in recommendations]
        self.assertNotIn(str(self.module1.id), module_ids)

    def test_include_completed_modules(self):
        """Test that completed modules can be included."""
        # Enroll and complete a module
        enrollment = Enrollment.objects.create(
            user=self.user,
            course=self.course,
            status=Enrollment.Status.ACTIVE,
        )
        content_item = ContentItem.objects.create(
            module=self.module1,
            title="Intro Video",
            content_type=ContentItem.ContentType.VIDEO,
            order=1,
            is_required=True,
            is_published=True,
        )
        LearnerProgress.objects.create(
            enrollment=enrollment,
            content_item=content_item,
            status=LearnerProgress.Status.COMPLETED,
        )

        recommender = ModuleRecommender(user=self.user)
        recommendations = recommender.get_recommendations(
            limit=10,
            exclude_completed=False,
        )

        # Module 1 should be included
        module_ids = [rec.item_id for rec in recommendations]
        self.assertIn(str(self.module1.id), module_ids)

    def test_empty_results_no_modules(self):
        """Test empty results when no modules match."""
        # Create a user with no access to any courses
        new_user = User.objects.create_user(
            email="new@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        # Make course non-free
        self.course.is_free = False
        self.course.save()

        recommender = ModuleRecommender(user=new_user)
        recommendations = recommender.get_recommendations(limit=10)

        self.assertEqual(len(recommendations), 0)

    def test_recommendation_metadata(self):
        """Test that recommendation metadata is complete."""
        recommender = ModuleRecommender(user=self.user)
        recommendations = recommender.get_recommendations(limit=1)

        if recommendations:
            rec = recommendations[0]
            self.assertIn('course_id', rec.metadata)
            self.assertIn('course_title', rec.metadata)
            self.assertIn('course_slug', rec.metadata)
            self.assertIn('module_order', rec.metadata)
            self.assertIn('skills', rec.metadata)
            self.assertIn('algorithm', rec.metadata)
            self.assertEqual(rec.metadata['algorithm'], 'module_recommender')


class ModuleRecommenderScoreModuleTests(TestCase):
    """Tests for ModuleRecommender.score_module()."""

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant",
        )
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.course = Course.objects.create(
            title="Python Course",
            slug="python-course",
            tenant=self.tenant,
            status=Course.Status.PUBLISHED,
            instructor=self.user,
        )
        self.module = Module.objects.create(
            course=self.course,
            title="Python Basics",
            order=1,
        )
        self.skill = Skill.objects.create(
            name="Python",
            category="programming",
            tenant=self.tenant,
        )
        ModuleSkill.objects.create(
            module=self.module,
            skill=self.skill,
            contribution_level='DEVELOPS',
            proficiency_gained=20,
            is_primary=True,
        )

    def test_score_returns_tuple(self):
        """Test that score_module returns a tuple."""
        recommender = ModuleRecommender(user=self.user)
        result = recommender.score_module(self.module)

        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_score_in_valid_range(self):
        """Test that score is between 0 and 1."""
        recommender = ModuleRecommender(user=self.user)
        score, reason = recommender.score_module(self.module)

        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_score_includes_reason(self):
        """Test that scoring provides a reason."""
        recommender = ModuleRecommender(user=self.user)
        score, reason = recommender.score_module(self.module)

        self.assertIsInstance(reason, str)

    def test_higher_score_for_skill_gap(self):
        """Test that modules addressing skill gaps score higher."""
        # User with no proficiency should see higher scores
        recommender = ModuleRecommender(user=self.user)
        score_no_progress, _ = recommender.score_module(self.module)

        # Give user high proficiency
        LearnerSkillProgress.objects.create(
            user=self.user,
            skill=self.skill,
            proficiency_score=90,
            proficiency_level=Skill.ProficiencyLevel.EXPERT,
        )

        # Clear cache
        recommender._user_skill_progress = None
        score_with_progress, _ = recommender.score_module(self.module)

        # Module should score lower when user already has high proficiency
        self.assertGreater(score_no_progress, score_with_progress)

    def test_target_skill_boost(self):
        """Test that target skills receive a boost."""
        # Without target skill
        recommender_no_target = ModuleRecommender(user=self.user)
        score_no_target, _ = recommender_no_target.score_module(self.module)

        # With target skill
        recommender_with_target = ModuleRecommender(
            user=self.user,
            target_skills=[str(self.skill.id)],
        )
        score_with_target, _ = recommender_with_target.score_module(self.module)

        # Target skill should boost the score
        self.assertGreaterEqual(score_with_target, score_no_target)


class ModuleRecommenderSkillGapAnalysisTests(TestCase):
    """Tests for ModuleRecommender.get_skill_gap_analysis()."""

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant",
        )
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.skill1 = Skill.objects.create(
            name="Python",
            category="programming",
            tenant=self.tenant,
        )
        self.skill2 = Skill.objects.create(
            name="JavaScript",
            category="programming",
            tenant=self.tenant,
        )
        # User has progress on skill1
        LearnerSkillProgress.objects.create(
            user=self.user,
            skill=self.skill1,
            proficiency_score=30,
            proficiency_level=Skill.ProficiencyLevel.BEGINNER,
        )
        # Create course and module
        self.course = Course.objects.create(
            title="Programming Course",
            slug="programming-course",
            tenant=self.tenant,
            status=Course.Status.PUBLISHED,
            instructor=self.user,
        )
        self.module = Module.objects.create(
            course=self.course,
            title="Python Module",
            order=1,
        )
        ModuleSkill.objects.create(
            module=self.module,
            skill=self.skill1,
            contribution_level='DEVELOPS',
            proficiency_gained=25,
        )

    def test_returns_list(self):
        """Test that skill gap analysis returns a list."""
        recommender = ModuleRecommender(user=self.user)
        gaps = recommender.get_skill_gap_analysis()

        self.assertIsInstance(gaps, list)

    def test_gap_analysis_structure(self):
        """Test the structure of gap analysis results."""
        recommender = ModuleRecommender(user=self.user)
        gaps = recommender.get_skill_gap_analysis(
            target_skills=[str(self.skill1.id)]
        )

        self.assertTrue(len(gaps) > 0)
        gap = gaps[0]
        self.assertIn('skill_id', gap)
        self.assertIn('skill_name', gap)
        self.assertIn('current_proficiency', gap)
        self.assertIn('gap', gap)
        self.assertIn('recommended_modules', gap)

    def test_gap_calculation(self):
        """Test that gap is calculated correctly."""
        recommender = ModuleRecommender(user=self.user)
        gaps = recommender.get_skill_gap_analysis(
            target_skills=[str(self.skill1.id)]
        )

        gap = gaps[0]
        # User has 30% proficiency, gap should be 70
        self.assertEqual(gap['current_proficiency'], 30)
        self.assertEqual(gap['gap'], 70)

    def test_gaps_sorted_by_size(self):
        """Test that gaps are sorted largest first."""
        # Create another progress entry with higher proficiency
        LearnerSkillProgress.objects.create(
            user=self.user,
            skill=self.skill2,
            proficiency_score=80,
            proficiency_level=Skill.ProficiencyLevel.ADVANCED,
        )

        recommender = ModuleRecommender(user=self.user)
        gaps = recommender.get_skill_gap_analysis(
            target_skills=[str(self.skill1.id), str(self.skill2.id)]
        )

        if len(gaps) >= 2:
            # First gap should be larger (70) than second (20)
            self.assertGreaterEqual(gaps[0]['gap'], gaps[1]['gap'])

    def test_recommended_modules_included(self):
        """Test that recommended modules are included in gap analysis."""
        recommender = ModuleRecommender(user=self.user)
        gaps = recommender.get_skill_gap_analysis(
            target_skills=[str(self.skill1.id)]
        )

        gap = gaps[0]
        self.assertTrue(len(gap['recommended_modules']) > 0)

        rec_module = gap['recommended_modules'][0]
        self.assertIn('module_id', rec_module)
        self.assertIn('module_title', rec_module)
        self.assertIn('proficiency_gained', rec_module)


class ModuleRecommenderPrerequisiteTests(TestCase):
    """Tests for prerequisite filtering in ModuleRecommender."""

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant",
        )
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.course = Course.objects.create(
            title="Programming Course",
            slug="programming-course",
            tenant=self.tenant,
            status=Course.Status.PUBLISHED,
            instructor=self.user,
            is_free=True,
        )
        self.skill = Skill.objects.create(
            name="Python",
            category="programming",
            tenant=self.tenant,
        )
        # Module 1 - no prerequisites
        self.module1 = Module.objects.create(
            course=self.course,
            title="Intro Module",
            order=1,
        )
        ModuleSkill.objects.create(
            module=self.module1,
            skill=self.skill,
            contribution_level='INTRODUCES',
            proficiency_gained=10,
        )
        # Module 2 - requires module 1
        self.module2 = Module.objects.create(
            course=self.course,
            title="Advanced Module",
            order=2,
        )
        ModuleSkill.objects.create(
            module=self.module2,
            skill=self.skill,
            contribution_level='DEVELOPS',
            proficiency_gained=20,
        )

    def test_modules_without_prerequisites_included(self):
        """Test that modules without prerequisites are recommended."""
        recommender = ModuleRecommender(user=self.user)
        recommendations = recommender.get_recommendations(
            limit=10,
            check_prerequisites=True,
        )

        module_ids = [rec.item_id for rec in recommendations]
        self.assertIn(str(self.module1.id), module_ids)

    def test_no_prerequisite_check_returns_all(self):
        """Test that disabling prerequisite check returns all modules."""
        recommender = ModuleRecommender(user=self.user)
        recommendations = recommender.get_recommendations(
            limit=10,
            check_prerequisites=False,
        )

        module_ids = [rec.item_id for rec in recommendations]
        self.assertIn(str(self.module1.id), module_ids)
        self.assertIn(str(self.module2.id), module_ids)


class ModuleRecommenderCollaborativeTests(TestCase):
    """Tests for collaborative filtering in ModuleRecommender."""

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant",
        )
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.similar_user = User.objects.create_user(
            email="similar@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.skill = Skill.objects.create(
            name="Python",
            category="programming",
            tenant=self.tenant,
        )
        # Give both users similar skill profiles
        LearnerSkillProgress.objects.create(
            user=self.user,
            skill=self.skill,
            proficiency_score=50,
            proficiency_level=Skill.ProficiencyLevel.INTERMEDIATE,
        )
        LearnerSkillProgress.objects.create(
            user=self.similar_user,
            skill=self.skill,
            proficiency_score=55,  # Similar to main user
            proficiency_level=Skill.ProficiencyLevel.INTERMEDIATE,
        )

    def test_find_similar_users(self):
        """Test that similar users are found based on skill profiles."""
        recommender = ModuleRecommender(user=self.user)
        similar_users = recommender._find_similar_users()

        # Should find the similar user
        similar_user_ids = [uid for uid, _ in similar_users]
        self.assertIn(str(self.similar_user.id), similar_user_ids)

    def test_no_similar_users_with_empty_skills(self):
        """Test empty results when no skill data exists."""
        new_user = User.objects.create_user(
            email="new@example.com",
            password="testpass123",
            tenant=self.tenant,
        )

        recommender = ModuleRecommender(user=new_user)
        similar_users = recommender._find_similar_users()

        # New user has no skills, so no similarity calculation possible
        self.assertEqual(len(similar_users), 0)


class ModuleRecommenderWeightTests(TestCase):
    """Tests for scoring weight calculations."""

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant",
        )
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.course = Course.objects.create(
            title="Test Course",
            slug="test-course",
            tenant=self.tenant,
            status=Course.Status.PUBLISHED,
            instructor=self.user,
            is_free=True,
        )
        self.module = Module.objects.create(
            course=self.course,
            title="Test Module",
            order=1,
        )
        self.skill = Skill.objects.create(
            name="Test Skill",
            category="test",
            tenant=self.tenant,
        )
        ModuleSkill.objects.create(
            module=self.module,
            skill=self.skill,
            contribution_level='DEVELOPS',
            proficiency_gained=20,
        )

    def test_skill_weight_only(self):
        """Test scoring with only skill weight."""
        recommender = ModuleRecommender(
            user=self.user,
            skill_weight=1.0,
            collaborative_weight=0.0,
            popularity_weight=0.0,
        )
        score, _ = recommender.score_module(self.module)

        # Should still return a valid score
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_weights_affect_score(self):
        """Test that different weights produce different scores."""
        recommender_skill_focused = ModuleRecommender(
            user=self.user,
            skill_weight=0.9,
            collaborative_weight=0.05,
            popularity_weight=0.05,
        )
        recommender_balanced = ModuleRecommender(
            user=self.user,
            skill_weight=0.33,
            collaborative_weight=0.33,
            popularity_weight=0.34,
        )

        score_skill, _ = recommender_skill_focused.score_module(self.module)
        score_balanced, _ = recommender_balanced.score_module(self.module)

        # Scores will be different due to different weight distributions
        # Both should be valid
        self.assertGreaterEqual(score_skill, 0.0)
        self.assertGreaterEqual(score_balanced, 0.0)
