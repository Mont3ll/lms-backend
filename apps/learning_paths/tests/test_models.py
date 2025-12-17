"""Tests for Learning Paths models."""

from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from apps.core.models import Tenant
from apps.courses.models import Course, Module
from apps.learning_paths.models import (
    LearningPath,
    LearningPathProgress,
    LearningPathStep,
    LearningPathStepProgress,
    PersonalizedLearningPath,
    PersonalizedPathProgress,
    PersonalizedPathStep,
)
from apps.skills.models import Skill
from apps.users.models import User


class LearningPathTests(TestCase):
    """Tests for the LearningPath model."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")

    def test_create_learning_path(self):
        """Test creating a learning path."""
        path = LearningPath.objects.create(
            tenant=self.tenant,
            title="Python Fundamentals Path",
            description="A comprehensive path for learning Python",
            status=LearningPath.Status.DRAFT,
        )

        self.assertEqual(path.title, "Python Fundamentals Path")
        self.assertEqual(path.tenant, self.tenant)
        self.assertEqual(path.status, LearningPath.Status.DRAFT)
        self.assertTrue(path.slug)  # Auto-generated

    def test_learning_path_str(self):
        """Test string representation of LearningPath."""
        path = LearningPath.objects.create(
            tenant=self.tenant,
            title="Django Master Path",
        )
        self.assertEqual(str(path), "Django Master Path (Test Tenant)")

    def test_learning_path_auto_slug(self):
        """Test that slug is auto-generated from title."""
        path = LearningPath.objects.create(
            tenant=self.tenant,
            title="Web Development Path",
        )
        self.assertIn("web-development", path.slug.lower())

    def test_learning_path_custom_slug(self):
        """Test that custom slug is preserved."""
        path = LearningPath.objects.create(
            tenant=self.tenant,
            title="Web Development Path",
            slug="my-custom-slug",
        )
        self.assertEqual(path.slug, "my-custom-slug")

    def test_learning_path_status_choices(self):
        """Test all status choices work correctly."""
        for status_choice, _ in LearningPath.Status.choices:
            path = LearningPath.objects.create(
                tenant=self.tenant,
                title=f"Path {status_choice}",
                status=status_choice,
            )
            self.assertEqual(path.status, status_choice)


class LearningPathStepTests(TestCase):
    """Tests for the LearningPathStep model with GenericForeignKey."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.user = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.path = LearningPath.objects.create(
            tenant=self.tenant,
            title="Test Learning Path",
        )
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Python Basics",
            instructor=self.user,
        )

    def test_create_step_with_course(self):
        """Test creating a step that references a Course."""
        course_ct = ContentType.objects.get_for_model(Course)
        step = LearningPathStep.objects.create(
            learning_path=self.path,
            content_type=course_ct,
            object_id=self.course.id,
            order=1,
            is_required=True,
        )

        self.assertEqual(step.learning_path, self.path)
        self.assertEqual(step.content_object, self.course)
        self.assertEqual(step.order, 1)
        self.assertTrue(step.is_required)

    def test_create_step_with_module(self):
        """Test creating a step that references a Module."""
        module = Module.objects.create(
            course=self.course,
            title="Introduction",
            order=1,
        )
        module_ct = ContentType.objects.get_for_model(Module)
        
        step = LearningPathStep.objects.create(
            learning_path=self.path,
            content_type=module_ct,
            object_id=module.id,
            order=1,
        )

        self.assertEqual(step.content_object, module)

    def test_step_str(self):
        """Test string representation of LearningPathStep."""
        course_ct = ContentType.objects.get_for_model(Course)
        step = LearningPathStep.objects.create(
            learning_path=self.path,
            content_type=course_ct,
            object_id=self.course.id,
            order=1,
        )
        
        self.assertIn("Step 1:", str(step))
        self.assertIn("Python Basics", str(step))

    def test_step_unique_order_per_path(self):
        """Test that step orders are unique within a learning path."""
        course_ct = ContentType.objects.get_for_model(Course)
        LearningPathStep.objects.create(
            learning_path=self.path,
            content_type=course_ct,
            object_id=self.course.id,
            order=1,
        )
        
        course2 = Course.objects.create(
            tenant=self.tenant,
            title="Python Advanced",
            instructor=self.user,
        )
        
        # Same order in same path should raise error
        with self.assertRaises(IntegrityError):
            LearningPathStep.objects.create(
                learning_path=self.path,
                content_type=course_ct,
                object_id=course2.id,
                order=1,  # Same order
            )

    def test_step_same_order_different_paths(self):
        """Test that same order can exist in different paths."""
        course_ct = ContentType.objects.get_for_model(Course)
        
        path2 = LearningPath.objects.create(
            tenant=self.tenant,
            title="Another Path",
        )
        
        step1 = LearningPathStep.objects.create(
            learning_path=self.path,
            content_type=course_ct,
            object_id=self.course.id,
            order=1,
        )
        
        step2 = LearningPathStep.objects.create(
            learning_path=path2,
            content_type=course_ct,
            object_id=self.course.id,
            order=1,  # Same order, different path - should work
        )
        
        self.assertEqual(step1.order, step2.order)


class LearningPathProgressTests(TestCase):
    """Tests for the LearningPathProgress model."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.user = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.path = LearningPath.objects.create(
            tenant=self.tenant,
            title="Test Path",
            status=LearningPath.Status.PUBLISHED,
        )
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            instructor=self.instructor,
        )
        course_ct = ContentType.objects.get_for_model(Course)
        self.step = LearningPathStep.objects.create(
            learning_path=self.path,
            content_type=course_ct,
            object_id=self.course.id,
            order=1,
        )

    def test_create_progress(self):
        """Test creating learning path progress."""
        progress = LearningPathProgress.objects.create(
            user=self.user,
            learning_path=self.path,
        )

        self.assertEqual(progress.user, self.user)
        self.assertEqual(progress.learning_path, self.path)
        self.assertEqual(progress.status, LearningPathProgress.Status.NOT_STARTED)
        self.assertEqual(progress.current_step_order, 0)

    def test_progress_str(self):
        """Test string representation of LearningPathProgress."""
        progress = LearningPathProgress.objects.create(
            user=self.user,
            learning_path=self.path,
        )
        
        self.assertIn(self.user.email, str(progress))
        self.assertIn(self.path.title, str(progress))
        self.assertIn("NOT_STARTED", str(progress))

    def test_progress_unique_per_user_and_path(self):
        """Test that progress is unique per user and learning path."""
        LearningPathProgress.objects.create(
            user=self.user,
            learning_path=self.path,
        )

        with self.assertRaises(IntegrityError):
            LearningPathProgress.objects.create(
                user=self.user,
                learning_path=self.path,
            )

    def test_progress_percentage_empty_path(self):
        """Test progress percentage with no steps."""
        empty_path = LearningPath.objects.create(
            tenant=self.tenant,
            title="Empty Path",
        )
        progress = LearningPathProgress.objects.create(
            user=self.user,
            learning_path=empty_path,
        )

        self.assertEqual(progress.progress_percentage, 0)

    def test_progress_percentage_with_steps(self):
        """Test progress percentage calculation."""
        # Add a second step
        course2 = Course.objects.create(
            tenant=self.tenant,
            title="Course 2",
            instructor=self.instructor,
        )
        course_ct = ContentType.objects.get_for_model(Course)
        step2 = LearningPathStep.objects.create(
            learning_path=self.path,
            content_type=course_ct,
            object_id=course2.id,
            order=2,
        )

        progress = LearningPathProgress.objects.create(
            user=self.user,
            learning_path=self.path,
            status=LearningPathProgress.Status.IN_PROGRESS,
        )
        
        # Complete one step
        LearningPathStepProgress.objects.create(
            user=self.user,
            learning_path_progress=progress,
            step=self.step,
            status=LearningPathStepProgress.Status.COMPLETED,
        )
        
        # 1 out of 2 steps = 50%
        self.assertEqual(progress.progress_percentage, 50.0)


class LearningPathStepProgressTests(TestCase):
    """Tests for the LearningPathStepProgress model."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.user = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.path = LearningPath.objects.create(
            tenant=self.tenant,
            title="Test Path",
            status=LearningPath.Status.PUBLISHED,
        )
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            instructor=self.instructor,
        )
        course_ct = ContentType.objects.get_for_model(Course)
        self.step = LearningPathStep.objects.create(
            learning_path=self.path,
            content_type=course_ct,
            object_id=self.course.id,
            order=1,
        )
        self.path_progress = LearningPathProgress.objects.create(
            user=self.user,
            learning_path=self.path,
        )

    def test_create_step_progress(self):
        """Test creating step progress."""
        step_progress = LearningPathStepProgress.objects.create(
            user=self.user,
            learning_path_progress=self.path_progress,
            step=self.step,
        )

        self.assertEqual(step_progress.user, self.user)
        self.assertEqual(step_progress.step, self.step)
        self.assertEqual(step_progress.status, LearningPathStepProgress.Status.NOT_STARTED)

    def test_step_progress_str(self):
        """Test string representation of LearningPathStepProgress."""
        step_progress = LearningPathStepProgress.objects.create(
            user=self.user,
            learning_path_progress=self.path_progress,
            step=self.step,
            status=LearningPathStepProgress.Status.IN_PROGRESS,
        )
        
        self.assertIn(self.user.email, str(step_progress))
        self.assertIn("Step 1", str(step_progress))
        self.assertIn("IN_PROGRESS", str(step_progress))

    def test_step_progress_unique_per_user_and_step(self):
        """Test that step progress is unique per user and step."""
        LearningPathStepProgress.objects.create(
            user=self.user,
            learning_path_progress=self.path_progress,
            step=self.step,
        )

        with self.assertRaises(IntegrityError):
            LearningPathStepProgress.objects.create(
                user=self.user,
                learning_path_progress=self.path_progress,
                step=self.step,
            )

    def test_step_progress_status_choices(self):
        """Test all status choices work correctly."""
        for status_choice, _ in LearningPathStepProgress.Status.choices:
            # Clean up previous to avoid unique constraint
            LearningPathStepProgress.objects.filter(
                user=self.user, step=self.step
            ).delete()
            
            step_progress = LearningPathStepProgress.objects.create(
                user=self.user,
                learning_path_progress=self.path_progress,
                step=self.step,
                status=status_choice,
            )
            self.assertEqual(step_progress.status, status_choice)


# =============================================================================
# Personalized Learning Path Model Tests
# =============================================================================


class PersonalizedLearningPathTests(TestCase):
    """Tests for the PersonalizedLearningPath model."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.user = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
            role=User.Role.INSTRUCTOR,
        )
        self.skill = Skill.objects.create(
            tenant=self.tenant,
            name="Python Programming",
            category=Skill.Category.TECHNICAL,
        )

    def test_create_personalized_path(self):
        """Test creating a personalized learning path."""
        path = PersonalizedLearningPath.objects.create(
            user=self.user,
            tenant=self.tenant,
            title="Python Skill Gap Recovery",
            description="A personalized path to address Python skill gaps",
            generation_type=PersonalizedLearningPath.GenerationType.SKILL_GAP,
            estimated_duration=20,
        )

        self.assertEqual(path.user, self.user)
        self.assertEqual(path.tenant, self.tenant)
        self.assertEqual(path.title, "Python Skill Gap Recovery")
        self.assertEqual(path.generation_type, PersonalizedLearningPath.GenerationType.SKILL_GAP)
        self.assertEqual(path.status, PersonalizedLearningPath.Status.ACTIVE)
        self.assertEqual(path.estimated_duration, 20)
        self.assertIsNotNone(path.generated_at)

    def test_personalized_path_str(self):
        """Test string representation of PersonalizedLearningPath."""
        path = PersonalizedLearningPath.objects.create(
            user=self.user,
            tenant=self.tenant,
            title="Remedial Path",
            generation_type=PersonalizedLearningPath.GenerationType.REMEDIAL,
            estimated_duration=10,
        )
        
        expected_str = f"Remedial Path - {self.user.email} (REMEDIAL)"
        self.assertEqual(str(path), expected_str)

    def test_personalized_path_generation_types(self):
        """Test all generation type choices work correctly."""
        for gen_type, _ in PersonalizedLearningPath.GenerationType.choices:
            path = PersonalizedLearningPath.objects.create(
                user=self.user,
                tenant=self.tenant,
                title=f"Path {gen_type}",
                generation_type=gen_type,
                estimated_duration=5,
            )
            self.assertEqual(path.generation_type, gen_type)

    def test_personalized_path_status_choices(self):
        """Test all status choices work correctly."""
        for status_choice, _ in PersonalizedLearningPath.Status.choices:
            path = PersonalizedLearningPath.objects.create(
                user=self.user,
                tenant=self.tenant,
                title=f"Path {status_choice}",
                generation_type=PersonalizedLearningPath.GenerationType.GOAL_BASED,
                status=status_choice,
                estimated_duration=5,
            )
            self.assertEqual(path.status, status_choice)

    def test_personalized_path_with_target_skills(self):
        """Test adding target skills to a personalized path."""
        skill2 = Skill.objects.create(
            tenant=self.tenant,
            name="Django Framework",
            category=Skill.Category.TECHNICAL,
        )
        
        path = PersonalizedLearningPath.objects.create(
            user=self.user,
            tenant=self.tenant,
            title="Full Stack Path",
            generation_type=PersonalizedLearningPath.GenerationType.SKILL_GAP,
            estimated_duration=40,
        )
        path.target_skills.add(self.skill, skill2)

        self.assertEqual(path.target_skills.count(), 2)
        self.assertIn(self.skill, path.target_skills.all())
        self.assertIn(skill2, path.target_skills.all())

    def test_personalized_path_is_expired_false(self):
        """Test is_expired property when path is not expired."""
        path = PersonalizedLearningPath.objects.create(
            user=self.user,
            tenant=self.tenant,
            title="Active Path",
            generation_type=PersonalizedLearningPath.GenerationType.ONBOARDING,
            estimated_duration=10,
            expires_at=timezone.now() + timedelta(days=30),
        )

        self.assertFalse(path.is_expired)

    def test_personalized_path_is_expired_true(self):
        """Test is_expired property when path is expired."""
        path = PersonalizedLearningPath.objects.create(
            user=self.user,
            tenant=self.tenant,
            title="Expired Path",
            generation_type=PersonalizedLearningPath.GenerationType.ONBOARDING,
            estimated_duration=10,
            expires_at=timezone.now() - timedelta(days=1),
        )

        self.assertTrue(path.is_expired)

    def test_personalized_path_is_expired_no_expiry(self):
        """Test is_expired property when no expiry date set."""
        path = PersonalizedLearningPath.objects.create(
            user=self.user,
            tenant=self.tenant,
            title="No Expiry Path",
            generation_type=PersonalizedLearningPath.GenerationType.SKILL_GAP,
            estimated_duration=10,
            expires_at=None,
        )

        self.assertFalse(path.is_expired)

    def test_personalized_path_generation_params(self):
        """Test generation_params JSONField."""
        params = {
            "skill_gap_threshold": 0.7,
            "max_modules": 10,
            "include_prerequisites": True,
        }
        
        path = PersonalizedLearningPath.objects.create(
            user=self.user,
            tenant=self.tenant,
            title="Custom Path",
            generation_type=PersonalizedLearningPath.GenerationType.SKILL_GAP,
            estimated_duration=15,
            generation_params=params,
        )

        self.assertEqual(path.generation_params["skill_gap_threshold"], 0.7)
        self.assertEqual(path.generation_params["max_modules"], 10)
        self.assertTrue(path.generation_params["include_prerequisites"])

    def test_personalized_path_total_steps(self):
        """Test total_steps property."""
        course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            instructor=self.instructor,
        )
        module1 = Module.objects.create(course=course, title="Module 1", order=1)
        module2 = Module.objects.create(course=course, title="Module 2", order=2)
        
        path = PersonalizedLearningPath.objects.create(
            user=self.user,
            tenant=self.tenant,
            title="Test Path",
            generation_type=PersonalizedLearningPath.GenerationType.SKILL_GAP,
            estimated_duration=10,
        )
        
        PersonalizedPathStep.objects.create(
            path=path, module=module1, order=1, estimated_duration=30
        )
        PersonalizedPathStep.objects.create(
            path=path, module=module2, order=2, estimated_duration=45
        )

        self.assertEqual(path.total_steps, 2)

    def test_personalized_path_required_steps_count(self):
        """Test required_steps_count property."""
        course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            instructor=self.instructor,
        )
        module1 = Module.objects.create(course=course, title="Module 1", order=1)
        module2 = Module.objects.create(course=course, title="Module 2", order=2)
        module3 = Module.objects.create(course=course, title="Module 3", order=3)
        
        path = PersonalizedLearningPath.objects.create(
            user=self.user,
            tenant=self.tenant,
            title="Test Path",
            generation_type=PersonalizedLearningPath.GenerationType.SKILL_GAP,
            estimated_duration=10,
        )
        
        PersonalizedPathStep.objects.create(
            path=path, module=module1, order=1, is_required=True, estimated_duration=30
        )
        PersonalizedPathStep.objects.create(
            path=path, module=module2, order=2, is_required=True, estimated_duration=45
        )
        PersonalizedPathStep.objects.create(
            path=path, module=module3, order=3, is_required=False, estimated_duration=20
        )

        self.assertEqual(path.required_steps_count, 2)


class PersonalizedPathStepTests(TestCase):
    """Tests for the PersonalizedPathStep model."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.user = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
            role=User.Role.INSTRUCTOR,
        )
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            instructor=self.instructor,
        )
        self.module = Module.objects.create(
            course=self.course,
            title="Test Module",
            order=1,
        )
        self.path = PersonalizedLearningPath.objects.create(
            user=self.user,
            tenant=self.tenant,
            title="Test Path",
            generation_type=PersonalizedLearningPath.GenerationType.SKILL_GAP,
            estimated_duration=10,
        )
        self.skill = Skill.objects.create(
            tenant=self.tenant,
            name="Python",
            category=Skill.Category.TECHNICAL,
        )

    def test_create_personalized_step(self):
        """Test creating a personalized path step."""
        step = PersonalizedPathStep.objects.create(
            path=self.path,
            module=self.module,
            order=1,
            is_required=True,
            reason="This module addresses your Python skill gap.",
            estimated_duration=30,
        )

        self.assertEqual(step.path, self.path)
        self.assertEqual(step.module, self.module)
        self.assertEqual(step.order, 1)
        self.assertTrue(step.is_required)
        self.assertIn("Python skill gap", step.reason)
        self.assertEqual(step.estimated_duration, 30)

    def test_personalized_step_str(self):
        """Test string representation of PersonalizedPathStep."""
        step = PersonalizedPathStep.objects.create(
            path=self.path,
            module=self.module,
            order=1,
            estimated_duration=30,
        )
        
        expected_str = f"Step 1: {self.module.title} (Path: {self.path.title})"
        self.assertEqual(str(step), expected_str)

    def test_step_unique_order_per_path(self):
        """Test that step orders are unique within a personalized path."""
        PersonalizedPathStep.objects.create(
            path=self.path,
            module=self.module,
            order=1,
            estimated_duration=30,
        )
        
        module2 = Module.objects.create(
            course=self.course,
            title="Module 2",
            order=2,
        )
        
        # Same order in same path should raise error
        with self.assertRaises(IntegrityError):
            PersonalizedPathStep.objects.create(
                path=self.path,
                module=module2,
                order=1,  # Same order
                estimated_duration=45,
            )

    def test_step_same_order_different_paths(self):
        """Test that same order can exist in different paths."""
        path2 = PersonalizedLearningPath.objects.create(
            user=self.user,
            tenant=self.tenant,
            title="Another Path",
            generation_type=PersonalizedLearningPath.GenerationType.REMEDIAL,
            estimated_duration=10,
        )
        
        step1 = PersonalizedPathStep.objects.create(
            path=self.path,
            module=self.module,
            order=1,
            estimated_duration=30,
        )
        
        step2 = PersonalizedPathStep.objects.create(
            path=path2,
            module=self.module,
            order=1,  # Same order, different path - should work
            estimated_duration=30,
        )
        
        self.assertEqual(step1.order, step2.order)

    def test_step_with_target_skills(self):
        """Test adding target skills to a step."""
        skill2 = Skill.objects.create(
            tenant=self.tenant,
            name="Django",
            category=Skill.Category.TECHNICAL,
        )
        
        step = PersonalizedPathStep.objects.create(
            path=self.path,
            module=self.module,
            order=1,
            estimated_duration=30,
        )
        step.target_skills.add(self.skill, skill2)

        self.assertEqual(step.target_skills.count(), 2)
        self.assertIn(self.skill, step.target_skills.all())

    def test_step_optional(self):
        """Test creating an optional step."""
        step = PersonalizedPathStep.objects.create(
            path=self.path,
            module=self.module,
            order=1,
            is_required=False,
            reason="Optional bonus material",
            estimated_duration=15,
        )

        self.assertFalse(step.is_required)


class PersonalizedPathProgressTests(TestCase):
    """Tests for the PersonalizedPathProgress model."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.user = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
            role=User.Role.INSTRUCTOR,
        )
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            instructor=self.instructor,
        )
        self.module1 = Module.objects.create(
            course=self.course,
            title="Module 1",
            order=1,
        )
        self.module2 = Module.objects.create(
            course=self.course,
            title="Module 2",
            order=2,
        )
        self.path = PersonalizedLearningPath.objects.create(
            user=self.user,
            tenant=self.tenant,
            title="Test Path",
            generation_type=PersonalizedLearningPath.GenerationType.SKILL_GAP,
            estimated_duration=10,
        )
        self.step1 = PersonalizedPathStep.objects.create(
            path=self.path,
            module=self.module1,
            order=1,
            estimated_duration=30,
        )
        self.step2 = PersonalizedPathStep.objects.create(
            path=self.path,
            module=self.module2,
            order=2,
            estimated_duration=45,
        )

    def test_create_progress(self):
        """Test creating personalized path progress."""
        progress = PersonalizedPathProgress.objects.create(
            user=self.user,
            path=self.path,
        )

        self.assertEqual(progress.user, self.user)
        self.assertEqual(progress.path, self.path)
        self.assertEqual(progress.status, PersonalizedPathProgress.Status.NOT_STARTED)
        self.assertEqual(progress.current_step_order, 0)
        self.assertIsNone(progress.started_at)
        self.assertIsNone(progress.completed_at)

    def test_progress_str(self):
        """Test string representation of PersonalizedPathProgress."""
        progress = PersonalizedPathProgress.objects.create(
            user=self.user,
            path=self.path,
        )
        
        expected_str = f"{self.user.email} - {self.path.title} (NOT_STARTED)"
        self.assertEqual(str(progress), expected_str)

    def test_progress_unique_per_user_and_path(self):
        """Test that progress is unique per user and path."""
        PersonalizedPathProgress.objects.create(
            user=self.user,
            path=self.path,
        )

        with self.assertRaises(IntegrityError):
            PersonalizedPathProgress.objects.create(
                user=self.user,
                path=self.path,
            )

    def test_progress_status_choices(self):
        """Test all status choices work correctly."""
        for status_choice, _ in PersonalizedPathProgress.Status.choices:
            # Clean up previous to avoid unique constraint
            PersonalizedPathProgress.objects.filter(
                user=self.user, path=self.path
            ).delete()
            
            progress = PersonalizedPathProgress.objects.create(
                user=self.user,
                path=self.path,
                status=status_choice,
            )
            self.assertEqual(progress.status, status_choice)

    def test_progress_percentage_empty_path(self):
        """Test progress percentage with no steps."""
        empty_path = PersonalizedLearningPath.objects.create(
            user=self.user,
            tenant=self.tenant,
            title="Empty Path",
            generation_type=PersonalizedLearningPath.GenerationType.SKILL_GAP,
            estimated_duration=5,
        )
        progress = PersonalizedPathProgress.objects.create(
            user=self.user,
            path=empty_path,
        )

        self.assertEqual(progress.progress_percentage, 0)

    def test_current_step_not_started(self):
        """Test current_step property when not started."""
        progress = PersonalizedPathProgress.objects.create(
            user=self.user,
            path=self.path,
            current_step_order=0,
        )

        self.assertEqual(progress.current_step, self.step1)

    def test_current_step_in_progress(self):
        """Test current_step property when in progress."""
        progress = PersonalizedPathProgress.objects.create(
            user=self.user,
            path=self.path,
            current_step_order=1,
            status=PersonalizedPathProgress.Status.IN_PROGRESS,
        )

        self.assertEqual(progress.current_step, self.step1)

    def test_next_step_from_start(self):
        """Test next_step property when at start."""
        progress = PersonalizedPathProgress.objects.create(
            user=self.user,
            path=self.path,
            current_step_order=0,
        )

        self.assertEqual(progress.next_step, self.step1)

    def test_next_step_in_progress(self):
        """Test next_step property when in progress."""
        progress = PersonalizedPathProgress.objects.create(
            user=self.user,
            path=self.path,
            current_step_order=1,
            status=PersonalizedPathProgress.Status.IN_PROGRESS,
        )

        self.assertEqual(progress.next_step, self.step2)

    def test_next_step_at_end(self):
        """Test next_step property when at last step."""
        progress = PersonalizedPathProgress.objects.create(
            user=self.user,
            path=self.path,
            current_step_order=2,
            status=PersonalizedPathProgress.Status.IN_PROGRESS,
        )

        self.assertIsNone(progress.next_step)

    def test_progress_with_last_activity(self):
        """Test progress with last_activity_at timestamp."""
        now = timezone.now()
        progress = PersonalizedPathProgress.objects.create(
            user=self.user,
            path=self.path,
            status=PersonalizedPathProgress.Status.IN_PROGRESS,
            last_activity_at=now,
        )

        self.assertEqual(progress.last_activity_at, now)

    def test_progress_with_timestamps(self):
        """Test progress with started_at and completed_at timestamps."""
        started = timezone.now() - timedelta(days=7)
        completed = timezone.now()
        
        progress = PersonalizedPathProgress.objects.create(
            user=self.user,
            path=self.path,
            status=PersonalizedPathProgress.Status.COMPLETED,
            started_at=started,
            completed_at=completed,
        )

        self.assertEqual(progress.started_at, started)
        self.assertEqual(progress.completed_at, completed)
