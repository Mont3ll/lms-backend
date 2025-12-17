"""Tests for Learning Paths services."""

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from apps.core.models import Tenant
from apps.courses.models import Course
from apps.enrollments.models import Enrollment
from apps.learning_paths.models import (
    LearningPath,
    LearningPathProgress,
    LearningPathStep,
    LearningPathStepProgress,
)
from apps.learning_paths.services import LearningPathService
from apps.users.models import User


class EnrollInLearningPathTests(TestCase):
    """Tests for LearningPathService.enroll_in_learning_path with auto-enrollment."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        
        # Create courses
        self.course1 = Course.objects.create(
            tenant=self.tenant,
            title="Python Basics",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
        )
        self.course2 = Course.objects.create(
            tenant=self.tenant,
            title="Python Advanced",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
        )
        
        # Create a learning path with these courses as steps
        self.learning_path = LearningPath.objects.create(
            tenant=self.tenant,
            title="Python Learning Path",
            status=LearningPath.Status.PUBLISHED,
        )
        
        course_ct = ContentType.objects.get_for_model(Course)
        self.step1 = LearningPathStep.objects.create(
            learning_path=self.learning_path,
            content_type=course_ct,
            object_id=self.course1.id,
            order=1,
            is_required=True,
        )
        self.step2 = LearningPathStep.objects.create(
            learning_path=self.learning_path,
            content_type=course_ct,
            object_id=self.course2.id,
            order=2,
            is_required=True,
        )

    def test_enroll_creates_path_progress(self):
        """Test that enrolling creates a LearningPathProgress record."""
        progress, created, enrollments = LearningPathService.enroll_in_learning_path(
            user=self.learner,
            learning_path=self.learning_path
        )
        
        self.assertTrue(created)
        self.assertEqual(progress.user, self.learner)
        self.assertEqual(progress.learning_path, self.learning_path)
        self.assertEqual(progress.status, LearningPathProgress.Status.NOT_STARTED)

    def test_enroll_creates_step_progress(self):
        """Test that enrolling creates step progress for all steps."""
        progress, created, enrollments = LearningPathService.enroll_in_learning_path(
            user=self.learner,
            learning_path=self.learning_path
        )
        
        step_progress_count = LearningPathStepProgress.objects.filter(
            user=self.learner,
            learning_path_progress=progress
        ).count()
        
        self.assertEqual(step_progress_count, 2)

    def test_enroll_auto_enrolls_in_courses(self):
        """Test that enrolling auto-enrolls user in all courses within the path."""
        progress, created, enrollments = LearningPathService.enroll_in_learning_path(
            user=self.learner,
            learning_path=self.learning_path
        )
        
        self.assertEqual(len(enrollments), 2)
        
        # Verify course enrollments exist
        course1_enrollment = Enrollment.objects.filter(
            user=self.learner,
            course=self.course1,
            status=Enrollment.Status.ACTIVE
        ).exists()
        course2_enrollment = Enrollment.objects.filter(
            user=self.learner,
            course=self.course2,
            status=Enrollment.Status.ACTIVE
        ).exists()
        
        self.assertTrue(course1_enrollment)
        self.assertTrue(course2_enrollment)

    def test_enroll_returns_existing_enrollments(self):
        """Test that enrolling when user is already enrolled returns existing enrollments."""
        # Pre-enroll in one course
        Enrollment.objects.create(
            user=self.learner,
            course=self.course1,
            status=Enrollment.Status.ACTIVE,
        )
        
        progress, created, enrollments = LearningPathService.enroll_in_learning_path(
            user=self.learner,
            learning_path=self.learning_path
        )
        
        # Should still return 2 enrollments (1 existing + 1 new)
        self.assertEqual(len(enrollments), 2)
        
        # Should only have 2 enrollment records total (not 3)
        total_enrollments = Enrollment.objects.filter(user=self.learner).count()
        self.assertEqual(total_enrollments, 2)

    def test_enroll_syncs_existing_course_completion(self):
        """Test that enrolling syncs existing completed courses to step progress."""
        # Pre-complete one course
        enrollment = Enrollment.objects.create(
            user=self.learner,
            course=self.course1,
            status=Enrollment.Status.COMPLETED,
        )
        
        progress, created, enrollments = LearningPathService.enroll_in_learning_path(
            user=self.learner,
            learning_path=self.learning_path
        )
        
        # Step 1 should be marked as completed
        step1_progress = LearningPathStepProgress.objects.get(
            user=self.learner,
            learning_path_progress=progress,
            step=self.step1
        )
        self.assertEqual(step1_progress.status, LearningPathStepProgress.Status.COMPLETED)
        
        # Step 2 should still be not started
        step2_progress = LearningPathStepProgress.objects.get(
            user=self.learner,
            learning_path_progress=progress,
            step=self.step2
        )
        self.assertEqual(step2_progress.status, LearningPathStepProgress.Status.NOT_STARTED)

    def test_enroll_updates_path_progress_for_existing_completions(self):
        """Test that enrolling updates path progress status for existing completions."""
        # Pre-complete one course
        Enrollment.objects.create(
            user=self.learner,
            course=self.course1,
            status=Enrollment.Status.COMPLETED,
        )
        
        progress, created, enrollments = LearningPathService.enroll_in_learning_path(
            user=self.learner,
            learning_path=self.learning_path
        )
        
        # Path should be marked as in progress (not completed since only 1 of 2 courses done)
        progress.refresh_from_db()
        self.assertEqual(progress.status, LearningPathProgress.Status.IN_PROGRESS)

    def test_enroll_marks_path_completed_if_all_courses_done(self):
        """Test that enrolling marks path as completed if all courses are already done."""
        # Pre-complete both courses
        Enrollment.objects.create(
            user=self.learner,
            course=self.course1,
            status=Enrollment.Status.COMPLETED,
        )
        Enrollment.objects.create(
            user=self.learner,
            course=self.course2,
            status=Enrollment.Status.COMPLETED,
        )
        
        progress, created, enrollments = LearningPathService.enroll_in_learning_path(
            user=self.learner,
            learning_path=self.learning_path
        )
        
        progress.refresh_from_db()
        self.assertEqual(progress.status, LearningPathProgress.Status.COMPLETED)
        self.assertIsNotNone(progress.completed_at)

    def test_enroll_idempotent(self):
        """Test that enrolling multiple times is idempotent."""
        # First enrollment
        progress1, created1, enrollments1 = LearningPathService.enroll_in_learning_path(
            user=self.learner,
            learning_path=self.learning_path
        )
        
        # Second enrollment
        progress2, created2, enrollments2 = LearningPathService.enroll_in_learning_path(
            user=self.learner,
            learning_path=self.learning_path
        )
        
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(progress1.id, progress2.id)
        
        # Should still only have 2 course enrollments
        total_enrollments = Enrollment.objects.filter(user=self.learner).count()
        self.assertEqual(total_enrollments, 2)


class SyncCourseCompletionTests(TestCase):
    """Tests for LearningPathService.sync_course_completion_with_learning_paths."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        
        # Create a course
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Python Basics",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
        )
        
        # Create a learning path with this course as a step
        self.learning_path = LearningPath.objects.create(
            tenant=self.tenant,
            title="Python Learning Path",
            status=LearningPath.Status.PUBLISHED,
        )
        
        course_ct = ContentType.objects.get_for_model(Course)
        self.step = LearningPathStep.objects.create(
            learning_path=self.learning_path,
            content_type=course_ct,
            object_id=self.course.id,
            order=1,
            is_required=True,
        )
        
        # Create an enrollment
        self.enrollment = Enrollment.objects.create(
            user=self.learner,
            course=self.course,
            status=Enrollment.Status.ACTIVE,
        )

    def test_sync_does_nothing_for_non_completed_enrollment(self):
        """Test that sync returns False for non-completed enrollments."""
        result = LearningPathService.sync_course_completion_with_learning_paths(self.enrollment)
        
        self.assertFalse(result)
        # No progress should be created
        self.assertFalse(
            LearningPathProgress.objects.filter(
                user=self.learner,
                learning_path=self.learning_path
            ).exists()
        )

    def test_sync_creates_progress_for_completed_enrollment(self):
        """Test that sync creates learning path progress for completed enrollment."""
        self.enrollment.status = Enrollment.Status.COMPLETED
        self.enrollment.save()
        
        result = LearningPathService.sync_course_completion_with_learning_paths(self.enrollment)
        
        self.assertTrue(result)
        
        # Check path progress was created
        path_progress = LearningPathProgress.objects.get(
            user=self.learner,
            learning_path=self.learning_path
        )
        self.assertIsNotNone(path_progress)
        
        # Check step progress was created and marked completed
        step_progress = LearningPathStepProgress.objects.get(
            user=self.learner,
            learning_path_progress=path_progress,
            step=self.step
        )
        self.assertEqual(step_progress.status, LearningPathStepProgress.Status.COMPLETED)
        self.assertIsNotNone(step_progress.completed_at)

    def test_sync_marks_single_step_path_as_completed(self):
        """Test that completing the only step marks the path as completed."""
        self.enrollment.status = Enrollment.Status.COMPLETED
        self.enrollment.save()
        
        LearningPathService.sync_course_completion_with_learning_paths(self.enrollment)
        
        path_progress = LearningPathProgress.objects.get(
            user=self.learner,
            learning_path=self.learning_path
        )
        self.assertEqual(path_progress.status, LearningPathProgress.Status.COMPLETED)
        self.assertIsNotNone(path_progress.completed_at)

    def test_sync_marks_path_in_progress_for_multi_step(self):
        """Test that completing one step in multi-step path marks it in progress."""
        # Add a second step
        course2 = Course.objects.create(
            tenant=self.tenant,
            title="Python Advanced",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
        )
        course_ct = ContentType.objects.get_for_model(Course)
        LearningPathStep.objects.create(
            learning_path=self.learning_path,
            content_type=course_ct,
            object_id=course2.id,
            order=2,
            is_required=True,
        )
        
        self.enrollment.status = Enrollment.Status.COMPLETED
        self.enrollment.save()
        
        LearningPathService.sync_course_completion_with_learning_paths(self.enrollment)
        
        path_progress = LearningPathProgress.objects.get(
            user=self.learner,
            learning_path=self.learning_path
        )
        self.assertEqual(path_progress.status, LearningPathProgress.Status.IN_PROGRESS)
        self.assertIsNotNone(path_progress.started_at)
        self.assertIsNone(path_progress.completed_at)

    def test_sync_updates_existing_step_progress(self):
        """Test that sync updates existing step progress to completed."""
        # Create existing progress
        path_progress = LearningPathProgress.objects.create(
            user=self.learner,
            learning_path=self.learning_path,
            status=LearningPathProgress.Status.IN_PROGRESS,
        )
        step_progress = LearningPathStepProgress.objects.create(
            user=self.learner,
            learning_path_progress=path_progress,
            step=self.step,
            status=LearningPathStepProgress.Status.IN_PROGRESS,
        )
        
        self.enrollment.status = Enrollment.Status.COMPLETED
        self.enrollment.save()
        
        LearningPathService.sync_course_completion_with_learning_paths(self.enrollment)
        
        step_progress.refresh_from_db()
        self.assertEqual(step_progress.status, LearningPathStepProgress.Status.COMPLETED)

    def test_sync_ignores_draft_learning_paths(self):
        """Test that sync ignores draft learning paths."""
        self.learning_path.status = LearningPath.Status.DRAFT
        self.learning_path.save()
        
        self.enrollment.status = Enrollment.Status.COMPLETED
        self.enrollment.save()
        
        result = LearningPathService.sync_course_completion_with_learning_paths(self.enrollment)
        
        self.assertFalse(result)
        self.assertFalse(
            LearningPathProgress.objects.filter(
                user=self.learner,
                learning_path=self.learning_path
            ).exists()
        )

    def test_sync_ignores_other_tenant_learning_paths(self):
        """Test that sync only affects learning paths in the same tenant."""
        other_tenant = Tenant.objects.create(name="Other Tenant", slug="other-tenant")
        other_path = LearningPath.objects.create(
            tenant=other_tenant,
            title="Other Path",
            status=LearningPath.Status.PUBLISHED,
        )
        course_ct = ContentType.objects.get_for_model(Course)
        LearningPathStep.objects.create(
            learning_path=other_path,
            content_type=course_ct,
            object_id=self.course.id,  # Same course but different tenant path
            order=1,
        )
        
        self.enrollment.status = Enrollment.Status.COMPLETED
        self.enrollment.save()
        
        LearningPathService.sync_course_completion_with_learning_paths(self.enrollment)
        
        # Should only create progress for the same-tenant path
        self.assertTrue(
            LearningPathProgress.objects.filter(
                user=self.learner,
                learning_path=self.learning_path
            ).exists()
        )
        self.assertFalse(
            LearningPathProgress.objects.filter(
                user=self.learner,
                learning_path=other_path
            ).exists()
        )


class SyncCourseIncompletionTests(TestCase):
    """Tests for handling course incompletion (reverting from completed)."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Python Basics",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
        )
        
        self.learning_path = LearningPath.objects.create(
            tenant=self.tenant,
            title="Python Learning Path",
            status=LearningPath.Status.PUBLISHED,
        )
        
        course_ct = ContentType.objects.get_for_model(Course)
        self.step = LearningPathStep.objects.create(
            learning_path=self.learning_path,
            content_type=course_ct,
            object_id=self.course.id,
            order=1,
            is_required=True,
        )
        
        self.enrollment = Enrollment.objects.create(
            user=self.learner,
            course=self.course,
            status=Enrollment.Status.ACTIVE,
        )

    def test_sync_enrollment_status_change_handles_completion(self):
        """Test that sync_course_enrollment_with_learning_paths handles completion."""
        self.enrollment.status = Enrollment.Status.COMPLETED
        self.enrollment.save()
        
        result = LearningPathService.sync_course_enrollment_with_learning_paths(self.enrollment)
        
        self.assertTrue(result)
        path_progress = LearningPathProgress.objects.get(
            user=self.learner,
            learning_path=self.learning_path
        )
        self.assertEqual(path_progress.status, LearningPathProgress.Status.COMPLETED)

    def test_sync_reverts_step_when_course_becomes_active_again(self):
        """Test that reverting enrollment to active reverts step progress."""
        # First complete the course
        self.enrollment.status = Enrollment.Status.COMPLETED
        self.enrollment.save()
        LearningPathService.sync_course_completion_with_learning_paths(self.enrollment)
        
        # Now revert to active
        self.enrollment.status = Enrollment.Status.ACTIVE
        self.enrollment.save()
        result = LearningPathService.sync_course_enrollment_with_learning_paths(self.enrollment)
        
        self.assertTrue(result)
        step_progress = LearningPathStepProgress.objects.get(
            user=self.learner,
            step=self.step
        )
        self.assertEqual(step_progress.status, LearningPathStepProgress.Status.IN_PROGRESS)
        self.assertIsNone(step_progress.completed_at)


class UpdateLearningPathProgressTests(TestCase):
    """Tests for _update_learning_path_progress helper method."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
        )

    def test_empty_path_marked_completed(self):
        """Test that an empty learning path is marked as completed."""
        learning_path = LearningPath.objects.create(
            tenant=self.tenant,
            title="Empty Path",
            status=LearningPath.Status.PUBLISHED,
        )
        path_progress = LearningPathProgress.objects.create(
            user=self.learner,
            learning_path=learning_path,
            status=LearningPathProgress.Status.NOT_STARTED,
        )
        
        LearningPathService._update_learning_path_progress(path_progress)
        
        path_progress.refresh_from_db()
        self.assertEqual(path_progress.status, LearningPathProgress.Status.COMPLETED)

    def test_updates_current_step_order(self):
        """Test that current_step_order is updated to highest completed step."""
        learning_path = LearningPath.objects.create(
            tenant=self.tenant,
            title="Test Path",
            status=LearningPath.Status.PUBLISHED,
        )
        
        course1 = Course.objects.create(
            tenant=self.tenant,
            title="Course 1",
            instructor=self.instructor,
        )
        course2 = Course.objects.create(
            tenant=self.tenant,
            title="Course 2",
            instructor=self.instructor,
        )
        
        course_ct = ContentType.objects.get_for_model(Course)
        step1 = LearningPathStep.objects.create(
            learning_path=learning_path,
            content_type=course_ct,
            object_id=course1.id,
            order=1,
        )
        step2 = LearningPathStep.objects.create(
            learning_path=learning_path,
            content_type=course_ct,
            object_id=course2.id,
            order=2,
        )
        
        path_progress = LearningPathProgress.objects.create(
            user=self.learner,
            learning_path=learning_path,
            status=LearningPathProgress.Status.NOT_STARTED,
        )
        
        # Complete step 2 (higher order)
        LearningPathStepProgress.objects.create(
            user=self.learner,
            learning_path_progress=path_progress,
            step=step2,
            status=LearningPathStepProgress.Status.COMPLETED,
        )
        
        LearningPathService._update_learning_path_progress(path_progress)
        
        path_progress.refresh_from_db()
        self.assertEqual(path_progress.current_step_order, 2)
        self.assertEqual(path_progress.status, LearningPathProgress.Status.IN_PROGRESS)


# =============================================================================
# PersonalizedPathGenerator Tests
# =============================================================================


class PersonalizedPathGeneratorTests(TestCase):
    """Tests for the PersonalizedPathGenerator service."""

    def setUp(self):
        from apps.courses.models import Module, ContentItem
        from apps.skills.models import Skill, ModuleSkill, LearnerSkillProgress
        from apps.learning_paths.models import (
            PersonalizedLearningPath,
            PersonalizedPathStep,
            PersonalizedPathProgress
        )
        
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        
        # Create skills
        self.skill_python = Skill.objects.create(
            tenant=self.tenant,
            name="Python Programming",
            slug="python-programming",
            category=Skill.Category.TECHNICAL,
        )
        self.skill_django = Skill.objects.create(
            tenant=self.tenant,
            name="Django Framework",
            slug="django-framework",
            category=Skill.Category.TECHNICAL,
        )
        self.skill_rest = Skill.objects.create(
            tenant=self.tenant,
            name="REST APIs",
            slug="rest-apis",
            category=Skill.Category.TECHNICAL,
        )
        
        # Create courses and modules
        self.course1 = Course.objects.create(
            tenant=self.tenant,
            title="Python Fundamentals",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
        )
        self.module1 = Module.objects.create(
            course=self.course1,
            title="Python Basics",
            order=1,
        )
        self.module2 = Module.objects.create(
            course=self.course1,
            title="Python OOP",
            order=2,
        )
        
        self.course2 = Course.objects.create(
            tenant=self.tenant,
            title="Django Web Development",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
        )
        self.module3 = Module.objects.create(
            course=self.course2,
            title="Django Models",
            order=1,
        )
        self.module4 = Module.objects.create(
            course=self.course2,
            title="Django REST Framework",
            order=2,
        )
        
        # Create content items for modules (needed for duration estimation)
        ContentItem.objects.create(
            module=self.module1,
            title="Intro to Python",
            content_type=ContentItem.ContentType.VIDEO,
            order=1,
        )
        ContentItem.objects.create(
            module=self.module2,
            title="Classes and Objects",
            content_type=ContentItem.ContentType.DOCUMENT,
            order=1,
        )
        ContentItem.objects.create(
            module=self.module3,
            title="Django Models Guide",
            content_type=ContentItem.ContentType.DOCUMENT,
            order=1,
        )
        ContentItem.objects.create(
            module=self.module4,
            title="DRF Tutorial",
            content_type=ContentItem.ContentType.VIDEO,
            order=1,
        )
        
        # Create module-skill mappings
        ModuleSkill.objects.create(
            module=self.module1,
            skill=self.skill_python,
            contribution_level=ModuleSkill.ContributionLevel.INTRODUCES,
            proficiency_gained=25,
            is_primary=True,
        )
        ModuleSkill.objects.create(
            module=self.module2,
            skill=self.skill_python,
            contribution_level=ModuleSkill.ContributionLevel.DEVELOPS,
            proficiency_gained=30,
            is_primary=True,
        )
        ModuleSkill.objects.create(
            module=self.module3,
            skill=self.skill_django,
            contribution_level=ModuleSkill.ContributionLevel.INTRODUCES,
            proficiency_gained=20,
            is_primary=True,
        )
        ModuleSkill.objects.create(
            module=self.module3,
            skill=self.skill_python,
            contribution_level=ModuleSkill.ContributionLevel.REINFORCES,
            proficiency_gained=10,
            is_primary=False,
        )
        ModuleSkill.objects.create(
            module=self.module4,
            skill=self.skill_django,
            contribution_level=ModuleSkill.ContributionLevel.DEVELOPS,
            proficiency_gained=25,
            is_primary=True,
        )
        ModuleSkill.objects.create(
            module=self.module4,
            skill=self.skill_rest,
            contribution_level=ModuleSkill.ContributionLevel.INTRODUCES,
            proficiency_gained=30,
            is_primary=True,
        )

    def test_generate_path_with_target_skills(self):
        """Test generating a path for specific target skills."""
        from apps.learning_paths.services import PersonalizedPathGenerator
        from apps.learning_paths.models import (
            PersonalizedLearningPath,
            PersonalizedPathProgress
        )
        
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[self.skill_python],
            target_proficiency=70,
        )
        
        path = generator.generate(title="Learn Python")
        
        # Verify path was created
        self.assertIsInstance(path, PersonalizedLearningPath)
        self.assertEqual(path.user, self.learner)
        self.assertEqual(path.tenant, self.tenant)
        self.assertEqual(path.title, "Learn Python")
        self.assertEqual(path.generation_type, PersonalizedLearningPath.GenerationType.SKILL_GAP)
        self.assertEqual(path.status, PersonalizedLearningPath.Status.ACTIVE)
        
        # Verify steps were created
        self.assertGreater(path.steps.count(), 0)
        
        # Verify progress record was created
        progress = PersonalizedPathProgress.objects.get(user=self.learner, path=path)
        self.assertEqual(progress.status, PersonalizedPathProgress.Status.NOT_STARTED)
        
        # Verify target skills are linked
        self.assertIn(self.skill_python, path.target_skills.all())

    def test_generate_path_with_multiple_skills(self):
        """Test generating a path for multiple target skills."""
        from apps.learning_paths.services import PersonalizedPathGenerator
        
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[self.skill_python, self.skill_django, self.skill_rest],
            target_proficiency=50,
        )
        
        path = generator.generate()
        
        # Should include modules that cover these skills
        self.assertGreaterEqual(path.steps.count(), 2)
        
        # All target skills should be linked
        target_skills = list(path.target_skills.all())
        self.assertIn(self.skill_python, target_skills)
        self.assertIn(self.skill_django, target_skills)
        self.assertIn(self.skill_rest, target_skills)

    def test_generate_path_skips_small_gaps(self):
        """Test that skills with small gaps are not included."""
        from apps.skills.models import LearnerSkillProgress
        from apps.learning_paths.services import PersonalizedPathGenerator
        
        # Give the user high proficiency in Python
        LearnerSkillProgress.objects.create(
            user=self.learner,
            skill=self.skill_python,
            proficiency_score=65,  # Only 5 points below target of 70
        )
        
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[self.skill_python],
            target_proficiency=70,
        )
        
        # Should raise ValueError since gap is too small (< 10)
        with self.assertRaises(ValueError) as context:
            generator.generate()
        
        self.assertIn("No skill gaps found", str(context.exception))

    def test_generate_path_excludes_completed_modules(self):
        """Test that completed modules are excluded by default."""
        from apps.skills.models import LearnerSkillProgress
        from apps.learning_paths.services import PersonalizedPathGenerator
        from apps.enrollments.models import Enrollment, LearnerProgress
        from apps.courses.models import ContentItem
        
        # Enroll user and complete module1
        enrollment = Enrollment.objects.create(
            user=self.learner,
            course=self.course1,
            status=Enrollment.Status.ACTIVE,
        )
        
        # Complete all content in module1
        for content in self.module1.content_items.all():
            LearnerProgress.objects.create(
                enrollment=enrollment,
                content_item=content,
                status=LearnerProgress.Status.COMPLETED,
            )
        
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[self.skill_python],
            target_proficiency=70,
            include_completed_modules=False,
        )
        
        path = generator.generate()
        
        # module1 should not be in the path
        module_ids = [step.module.id for step in path.steps.all()]
        self.assertNotIn(self.module1.id, module_ids)
        # But module2 should be (if it addresses Python)
        self.assertIn(self.module2.id, module_ids)

    def test_generate_path_respects_max_modules(self):
        """Test that the path respects the max_modules limit."""
        from apps.learning_paths.services import PersonalizedPathGenerator
        
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[self.skill_python, self.skill_django, self.skill_rest],
            target_proficiency=100,  # High target to need more modules
            max_modules=2,
        )
        
        path = generator.generate()
        
        self.assertLessEqual(path.steps.count(), 2)

    def test_generate_path_step_ordering(self):
        """Test that steps are ordered correctly."""
        from apps.learning_paths.services import PersonalizedPathGenerator
        
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[self.skill_python, self.skill_django],
            target_proficiency=70,
        )
        
        path = generator.generate()
        
        # Verify steps have sequential ordering
        steps = list(path.steps.all().order_by('order'))
        for i, step in enumerate(steps, start=1):
            self.assertEqual(step.order, i)

    def test_generate_path_includes_reasons(self):
        """Test that each step includes a reason for inclusion."""
        from apps.learning_paths.services import PersonalizedPathGenerator
        
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[self.skill_python],
            target_proficiency=70,
        )
        
        path = generator.generate()
        
        for step in path.steps.all():
            self.assertIsNotNone(step.reason)
            self.assertGreater(len(step.reason), 0)

    def test_generate_path_estimates_duration(self):
        """Test that the path has estimated duration."""
        from apps.learning_paths.services import PersonalizedPathGenerator
        
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[self.skill_python],
            target_proficiency=70,
        )
        
        path = generator.generate()
        
        # Path should have estimated duration in hours
        self.assertGreater(path.estimated_duration, 0)
        
        # Each step should have estimated duration in minutes
        for step in path.steps.all():
            self.assertGreater(step.estimated_duration, 0)

    def test_generate_path_sets_expiry(self):
        """Test that the path has an expiry date."""
        from apps.learning_paths.services import PersonalizedPathGenerator
        from django.utils import timezone
        from datetime import timedelta
        
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[self.skill_python],
            target_proficiency=70,
        )
        
        path = generator.generate()
        
        # Expiry should be set to ~90 days from now
        self.assertIsNotNone(path.expires_at)
        expected_expiry = timezone.now() + timedelta(days=90)
        # Allow 1 day tolerance
        self.assertAlmostEqual(
            path.expires_at.timestamp(),
            expected_expiry.timestamp(),
            delta=86400  # 1 day in seconds
        )

    def test_generate_path_stores_generation_params(self):
        """Test that generation parameters are stored."""
        from apps.learning_paths.services import PersonalizedPathGenerator
        
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[self.skill_python],
            target_proficiency=80,
            max_modules=5,
        )
        
        path = generator.generate()
        
        params = path.generation_params
        self.assertIsNotNone(params)
        self.assertEqual(params.get('target_proficiency'), 80)
        self.assertEqual(params.get('max_modules'), 5)
        self.assertIn(str(self.skill_python.id), params.get('target_skill_ids', []))

    def test_generate_path_no_modules_raises_error(self):
        """Test that an error is raised when no modules address the skills."""
        from apps.skills.models import Skill
        from apps.learning_paths.services import PersonalizedPathGenerator
        
        # Create a skill with no module mappings
        orphan_skill = Skill.objects.create(
            tenant=self.tenant,
            name="Orphan Skill",
            slug="orphan-skill",
            category=Skill.Category.OTHER,
        )
        
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[orphan_skill],
            target_proficiency=70,
        )
        
        with self.assertRaises(ValueError) as context:
            generator.generate()
        
        self.assertIn("No modules found", str(context.exception))

    def test_regenerate_path_archives_old_path(self):
        """Test that regenerating a path archives the old one."""
        from apps.learning_paths.services import PersonalizedPathGenerator
        from apps.learning_paths.models import PersonalizedLearningPath
        
        # Generate initial path
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[self.skill_python],
            target_proficiency=70,
        )
        
        old_path = generator.generate(title="Original Path")
        old_path_id = old_path.id
        
        # Regenerate
        new_path = PersonalizedPathGenerator.regenerate_path(old_path)
        
        # Old path should be archived
        old_path.refresh_from_db()
        self.assertEqual(old_path.status, PersonalizedLearningPath.Status.ARCHIVED)
        
        # New path should be active
        self.assertEqual(new_path.status, PersonalizedLearningPath.Status.ACTIVE)
        self.assertNotEqual(new_path.id, old_path_id)

    def test_generate_path_with_auto_title(self):
        """Test that a title is auto-generated when not provided."""
        from apps.learning_paths.services import PersonalizedPathGenerator
        
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[self.skill_python, self.skill_django],
            target_proficiency=70,
        )
        
        path = generator.generate()  # No title provided
        
        self.assertIn("Learning Path:", path.title)
        self.assertIn("Python Programming", path.title)

    def test_skill_gap_priority(self):
        """Test that SkillGap priority is based on gap size."""
        from apps.learning_paths.services import SkillGap
        
        gap1 = SkillGap(skill=self.skill_python, current_score=20, target_score=70, gap=50)
        gap2 = SkillGap(skill=self.skill_django, current_score=40, target_score=70, gap=30)
        
        self.assertEqual(gap1.priority, 50)
        self.assertEqual(gap2.priority, 30)
        self.assertGreater(gap1.priority, gap2.priority)

    def test_module_candidate_efficiency_score(self):
        """Test that ModuleCandidate efficiency score is calculated correctly."""
        from apps.learning_paths.services import ModuleCandidate
        
        candidate = ModuleCandidate(
            module=self.module1,
            skills_addressed=[self.skill_python],
            total_skill_contribution=50,
            estimated_duration=10,
            prerequisite_modules=[],
            contribution_level="DEVELOPS",
        )
        
        self.assertEqual(candidate.efficiency_score, 5.0)  # 50 / 10
        
        # Test zero duration
        candidate_zero = ModuleCandidate(
            module=self.module2,
            skills_addressed=[self.skill_python],
            total_skill_contribution=50,
            estimated_duration=0,
            prerequisite_modules=[],
            contribution_level="DEVELOPS",
        )
        
        self.assertEqual(candidate_zero.efficiency_score, 0.0)


class PersonalizedPathGeneratorDifficultyTests(TestCase):
    """Tests for difficulty filtering in PersonalizedPathGenerator."""

    def setUp(self):
        from apps.courses.models import Module, ContentItem
        from apps.skills.models import Skill, ModuleSkill
        
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        
        # Create a skill to target
        self.skill_python = Skill.objects.create(
            tenant=self.tenant,
            name="Python Programming",
            slug="python-programming",
            category=Skill.Category.TECHNICAL,
        )
        
        # Create courses with different difficulty levels
        self.beginner_course = Course.objects.create(
            tenant=self.tenant,
            title="Python for Beginners",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
            difficulty_level=Course.DifficultyLevel.BEGINNER,
        )
        self.beginner_module = Module.objects.create(
            course=self.beginner_course,
            title="Beginner Python Basics",
            order=1,
        )
        ContentItem.objects.create(
            module=self.beginner_module,
            title="Intro to Python",
            content_type=ContentItem.ContentType.VIDEO,
            order=1,
        )
        ModuleSkill.objects.create(
            module=self.beginner_module,
            skill=self.skill_python,
            contribution_level=ModuleSkill.ContributionLevel.INTRODUCES,
            proficiency_gained=20,
            is_primary=True,
        )
        
        self.intermediate_course = Course.objects.create(
            tenant=self.tenant,
            title="Intermediate Python",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
            difficulty_level=Course.DifficultyLevel.INTERMEDIATE,
        )
        self.intermediate_module = Module.objects.create(
            course=self.intermediate_course,
            title="Intermediate Python Concepts",
            order=1,
        )
        ContentItem.objects.create(
            module=self.intermediate_module,
            title="Python Classes",
            content_type=ContentItem.ContentType.VIDEO,
            order=1,
        )
        ModuleSkill.objects.create(
            module=self.intermediate_module,
            skill=self.skill_python,
            contribution_level=ModuleSkill.ContributionLevel.DEVELOPS,
            proficiency_gained=30,
            is_primary=True,
        )
        
        self.advanced_course = Course.objects.create(
            tenant=self.tenant,
            title="Advanced Python",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
            difficulty_level=Course.DifficultyLevel.ADVANCED,
        )
        self.advanced_module = Module.objects.create(
            course=self.advanced_course,
            title="Advanced Python Patterns",
            order=1,
        )
        ContentItem.objects.create(
            module=self.advanced_module,
            title="Metaclasses",
            content_type=ContentItem.ContentType.VIDEO,
            order=1,
        )
        ModuleSkill.objects.create(
            module=self.advanced_module,
            skill=self.skill_python,
            contribution_level=ModuleSkill.ContributionLevel.MASTERS,
            proficiency_gained=40,
            is_primary=True,
        )

    def test_difficulty_any_includes_all_levels(self):
        """Test that DIFFICULTY_ANY includes modules from all difficulty levels."""
        from apps.learning_paths.services import PersonalizedPathGenerator
        
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[self.skill_python],
            target_proficiency=100,  # High target to include all modules
            difficulty_preference=PersonalizedPathGenerator.DIFFICULTY_ANY,
        )
        
        path = generator.generate()
        
        # Should include modules from all difficulty levels
        module_ids = [step.module.id for step in path.steps.all()]
        self.assertIn(self.beginner_module.id, module_ids)
        self.assertIn(self.intermediate_module.id, module_ids)
        self.assertIn(self.advanced_module.id, module_ids)

    def test_difficulty_beginner_filters_correctly(self):
        """Test that DIFFICULTY_BEGINNER only includes beginner modules."""
        from apps.learning_paths.services import PersonalizedPathGenerator
        
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[self.skill_python],
            target_proficiency=100,
            difficulty_preference=PersonalizedPathGenerator.DIFFICULTY_BEGINNER,
        )
        
        path = generator.generate()
        
        module_ids = [step.module.id for step in path.steps.all()]
        
        # Should only include beginner module
        self.assertIn(self.beginner_module.id, module_ids)
        self.assertNotIn(self.intermediate_module.id, module_ids)
        self.assertNotIn(self.advanced_module.id, module_ids)

    def test_difficulty_intermediate_filters_correctly(self):
        """Test that DIFFICULTY_INTERMEDIATE only includes intermediate modules."""
        from apps.learning_paths.services import PersonalizedPathGenerator
        
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[self.skill_python],
            target_proficiency=100,
            difficulty_preference=PersonalizedPathGenerator.DIFFICULTY_INTERMEDIATE,
        )
        
        path = generator.generate()
        
        module_ids = [step.module.id for step in path.steps.all()]
        
        # Should only include intermediate module
        self.assertNotIn(self.beginner_module.id, module_ids)
        self.assertIn(self.intermediate_module.id, module_ids)
        self.assertNotIn(self.advanced_module.id, module_ids)

    def test_difficulty_advanced_filters_correctly(self):
        """Test that DIFFICULTY_ADVANCED only includes advanced modules."""
        from apps.learning_paths.services import PersonalizedPathGenerator
        
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[self.skill_python],
            target_proficiency=100,
            difficulty_preference=PersonalizedPathGenerator.DIFFICULTY_ADVANCED,
        )
        
        path = generator.generate()
        
        module_ids = [step.module.id for step in path.steps.all()]
        
        # Should only include advanced module
        self.assertNotIn(self.beginner_module.id, module_ids)
        self.assertNotIn(self.intermediate_module.id, module_ids)
        self.assertIn(self.advanced_module.id, module_ids)

    def test_difficulty_progressive_orders_easier_first(self):
        """Test that DIFFICULTY_PROGRESSIVE orders modules from easier to harder."""
        from apps.learning_paths.services import PersonalizedPathGenerator
        
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[self.skill_python],
            target_proficiency=100,  # High target to include all modules
            difficulty_preference=PersonalizedPathGenerator.DIFFICULTY_PROGRESSIVE,
        )
        
        path = generator.generate()
        
        steps = list(path.steps.all().order_by('order'))
        
        # Should include all modules
        self.assertEqual(len(steps), 3)
        
        # Get difficulty order for each step
        difficulties = []
        for step in steps:
            course_difficulty = step.module.course.difficulty_level
            if course_difficulty == Course.DifficultyLevel.BEGINNER:
                difficulties.append(1)
            elif course_difficulty == Course.DifficultyLevel.INTERMEDIATE:
                difficulties.append(2)
            else:
                difficulties.append(3)
        
        # Verify easier modules come before harder ones (non-decreasing order)
        for i in range(len(difficulties) - 1):
            self.assertLessEqual(
                difficulties[i],
                difficulties[i + 1],
                f"Module at position {i} (difficulty {difficulties[i]}) should not come after "
                f"module at position {i+1} (difficulty {difficulties[i+1]})"
            )

    def test_difficulty_preference_stored_in_generation_params(self):
        """Test that difficulty_preference is stored in generation_params."""
        from apps.learning_paths.services import PersonalizedPathGenerator
        
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[self.skill_python],
            target_proficiency=70,
            difficulty_preference=PersonalizedPathGenerator.DIFFICULTY_PROGRESSIVE,
        )
        
        path = generator.generate()
        
        self.assertEqual(
            path.generation_params.get('difficulty_preference'),
            PersonalizedPathGenerator.DIFFICULTY_PROGRESSIVE
        )

    def test_regenerate_preserves_difficulty_preference(self):
        """Test that regenerating a path preserves the difficulty preference."""
        from apps.learning_paths.services import PersonalizedPathGenerator
        
        # Generate initial path with BEGINNER difficulty
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[self.skill_python],
            target_proficiency=50,
            difficulty_preference=PersonalizedPathGenerator.DIFFICULTY_BEGINNER,
        )
        
        original_path = generator.generate()
        
        # Regenerate
        new_path = PersonalizedPathGenerator.regenerate_path(original_path)
        
        # Should preserve difficulty preference
        self.assertEqual(
            new_path.generation_params.get('difficulty_preference'),
            PersonalizedPathGenerator.DIFFICULTY_BEGINNER
        )
        
        # New path should also only have beginner modules
        for step in new_path.steps.all():
            self.assertEqual(
                step.module.course.difficulty_level,
                Course.DifficultyLevel.BEGINNER
            )

    def test_get_difficulty_order(self):
        """Test the _get_difficulty_order method returns correct values."""
        from apps.learning_paths.services import PersonalizedPathGenerator
        
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[self.skill_python],
            target_proficiency=70,
        )
        
        # Test beginner module
        self.assertEqual(generator._get_difficulty_order(self.beginner_module), 1)
        
        # Test intermediate module
        self.assertEqual(generator._get_difficulty_order(self.intermediate_module), 2)
        
        # Test advanced module
        self.assertEqual(generator._get_difficulty_order(self.advanced_module), 3)

    def test_module_candidate_includes_difficulty_order(self):
        """Test that ModuleCandidate includes difficulty_order field."""
        from apps.learning_paths.services import PersonalizedPathGenerator, SkillGap
        
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[self.skill_python],
            target_proficiency=70,
        )
        
        skill_gaps = [SkillGap(
            skill=self.skill_python,
            current_score=0,
            target_score=70,
            gap=70
        )]
        
        candidates = generator._find_module_candidates(skill_gaps)
        
        # Find candidates by module and check difficulty_order
        beginner_candidate = next((c for c in candidates if c.module.id == self.beginner_module.id), None)
        intermediate_candidate = next((c for c in candidates if c.module.id == self.intermediate_module.id), None)
        advanced_candidate = next((c for c in candidates if c.module.id == self.advanced_module.id), None)
        
        self.assertIsNotNone(beginner_candidate)
        self.assertEqual(beginner_candidate.difficulty_order, 1)
        
        self.assertIsNotNone(intermediate_candidate)
        self.assertEqual(intermediate_candidate.difficulty_order, 2)
        
        self.assertIsNotNone(advanced_candidate)
        self.assertEqual(advanced_candidate.difficulty_order, 3)
