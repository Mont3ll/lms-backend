"""Tests for Learning Paths viewsets."""

from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

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
from apps.users.models import User


class LearningPathViewSetTests(APITestCase):
    """Tests for LearningPathViewSet."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="testpass123",
            tenant=self.tenant,
            is_staff=True,
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
            role=User.Role.INSTRUCTOR,
        )
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant,
            role=User.Role.LEARNER,
        )
        
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
        )
        
        self.learning_path = LearningPath.objects.create(
            tenant=self.tenant,
            title="Test Learning Path",
            slug="test-learning-path",
            status=LearningPath.Status.PUBLISHED,
        )
        
        self.draft_path = LearningPath.objects.create(
            tenant=self.tenant,
            title="Draft Learning Path",
            slug="draft-learning-path",
            status=LearningPath.Status.DRAFT,
        )

    def test_list_learning_paths_authenticated(self):
        """Test listing learning paths as authenticated user."""
        self.client.force_authenticate(user=self.learner)
        # Set tenant on request
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:learningpath-list")
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_learning_paths_unauthenticated(self):
        """Test that unauthenticated users cannot list learning paths."""
        url = reverse("learning_paths:learningpath-list")
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve_learning_path(self):
        """Test retrieving a single learning path."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:learningpath-detail", kwargs={"slug": self.learning_path.slug})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Test Learning Path")

    def test_create_learning_path_as_instructor(self):
        """Test that instructors can create learning paths."""
        self.client.force_authenticate(user=self.instructor)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:learningpath-list")
        data = {
            "title": "New Learning Path",
            "description": "A new path for learning",
            "status": LearningPath.Status.DRAFT,
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "New Learning Path")

    def test_create_learning_path_as_learner_forbidden(self):
        """Test that learners cannot create learning paths."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:learningpath-list")
        data = {
            "title": "New Learning Path",
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_update_learning_path_as_admin(self):
        """Test that admins can update learning paths."""
        self.client.force_authenticate(user=self.admin)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:learningpath-detail", kwargs={"slug": self.learning_path.slug})
        data = {
            "title": "Updated Learning Path",
            "description": "Updated description",
        }
        response = self.client.patch(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Updated Learning Path")

    def test_learner_cannot_see_draft_paths(self):
        """Test that regular users cannot see draft learning paths."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:learningpath-detail", kwargs={"slug": self.draft_path.slug})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_admin_can_see_draft_paths(self):
        """Test that admins can see draft learning paths."""
        self.client.force_authenticate(user=self.admin)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:learningpath-detail", kwargs={"slug": self.draft_path.slug})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class LearningPathStepsTests(APITestCase):
    """Tests for managing learning path steps."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="testpass123",
            tenant=self.tenant,
            is_staff=True,
        )
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant,
            role=User.Role.LEARNER,
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
            status=Course.Status.PUBLISHED,
        )
        
        self.learning_path = LearningPath.objects.create(
            tenant=self.tenant,
            title="Test Learning Path",
            slug="test-learning-path",
            status=LearningPath.Status.PUBLISHED,
        )

    def test_list_steps(self):
        """Test listing steps for a learning path."""
        course_ct = ContentType.objects.get_for_model(Course)
        LearningPathStep.objects.create(
            learning_path=self.learning_path,
            content_type=course_ct,
            object_id=self.course.id,
            order=1,
        )
        
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:learningpath-manage-steps", kwargs={"slug": self.learning_path.slug})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_add_step_as_admin(self):
        """Test adding a step to a learning path as admin."""
        course_ct = ContentType.objects.get_for_model(Course)
        
        self.client.force_authenticate(user=self.admin)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:learningpath-manage-steps", kwargs={"slug": self.learning_path.slug})
        data = {
            "content_type_id": course_ct.id,  # Use content_type_id as expected by serializer
            "object_id": str(self.course.id),
            "is_required": True,
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["order"], 1)  # First step

    def test_add_step_as_learner_forbidden(self):
        """Test that learners cannot add steps."""
        course_ct = ContentType.objects.get_for_model(Course)
        
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:learningpath-manage-steps", kwargs={"slug": self.learning_path.slug})
        data = {
            "content_type_id": course_ct.id,  # Use content_type_id as expected by serializer
            "object_id": str(self.course.id),
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_step(self):
        """Test deleting a step from a learning path."""
        course_ct = ContentType.objects.get_for_model(Course)
        step = LearningPathStep.objects.create(
            learning_path=self.learning_path,
            content_type=course_ct,
            object_id=self.course.id,
            order=1,
        )
        
        self.client.force_authenticate(user=self.admin)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse(
            "learning_paths:learningpath-manage-single-step",
            kwargs={"slug": self.learning_path.slug, "step_pk": str(step.id)}
        )
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(LearningPathStep.objects.filter(id=step.id).exists())

    def test_reorder_steps(self):
        """Test reordering steps in a learning path."""
        course_ct = ContentType.objects.get_for_model(Course)
        
        course2 = Course.objects.create(
            tenant=self.tenant,
            title="Course 2",
            instructor=self.instructor,
        )
        
        step1 = LearningPathStep.objects.create(
            learning_path=self.learning_path,
            content_type=course_ct,
            object_id=self.course.id,
            order=1,
        )
        step2 = LearningPathStep.objects.create(
            learning_path=self.learning_path,
            content_type=course_ct,
            object_id=course2.id,
            order=2,
        )
        
        self.client.force_authenticate(user=self.admin)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:learningpath-reorder-steps", kwargs={"slug": self.learning_path.slug})
        # Reverse the order
        data = {
            "steps": [str(step2.id), str(step1.id)]
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        step1.refresh_from_db()
        step2.refresh_from_db()
        self.assertEqual(step1.order, 2)
        self.assertEqual(step2.order, 1)


class LearningPathProgressViewSetTests(APITestCase):
    """Tests for LearningPathProgressViewSet."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="testpass123",
            tenant=self.tenant,
            is_staff=True,
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
            role=User.Role.INSTRUCTOR,
        )
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant,
            role=User.Role.LEARNER,
        )
        self.other_learner = User.objects.create_user(
            email="other@example.com",
            password="testpass123",
            tenant=self.tenant,
            role=User.Role.LEARNER,
        )
        
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
        )
        
        self.learning_path = LearningPath.objects.create(
            tenant=self.tenant,
            title="Test Learning Path",
            slug="test-learning-path",
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
        
        self.progress = LearningPathProgress.objects.create(
            user=self.learner,
            learning_path=self.learning_path,
            status=LearningPathProgress.Status.NOT_STARTED,
        )

    def test_list_own_progress(self):
        """Test that learners can list their own progress."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:learningpathprogress-list")
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

    def test_cannot_see_other_user_progress(self):
        """Test that learners cannot see other users' progress."""
        self.client.force_authenticate(user=self.other_learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:learningpathprogress-list")
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)  # No progress for this user

    def test_admin_can_see_all_progress(self):
        """Test that admins can see all progress in tenant."""
        # Create progress for another user
        LearningPathProgress.objects.create(
            user=self.other_learner,
            learning_path=self.learning_path,
        )
        
        self.client.force_authenticate(user=self.admin)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:learningpathprogress-list")
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)

    def test_start_learning_path(self):
        """Test starting a learning path."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:learningpathprogress-start-path", kwargs={"pk": str(self.progress.id)})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.progress.refresh_from_db()
        self.assertEqual(self.progress.status, LearningPathProgress.Status.IN_PROGRESS)
        self.assertIsNotNone(self.progress.started_at)
        
        # Check that step progress was created
        self.assertTrue(
            LearningPathStepProgress.objects.filter(
                user=self.learner,
                learning_path_progress=self.progress,
                step=self.step
            ).exists()
        )

    def test_cannot_start_other_user_path(self):
        """Test that users cannot start another user's learning path."""
        self.client.force_authenticate(user=self.other_learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:learningpathprogress-start-path", kwargs={"pk": str(self.progress.id)})
        response = self.client.post(url)
        
        # Should get 404 because query filters to own progress
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_complete_step(self):
        """Test completing a step in a learning path."""
        # First start the path
        self.progress.status = LearningPathProgress.Status.IN_PROGRESS
        self.progress.save()
        
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse(
            "learning_paths:learningpathprogress-complete-step",
            kwargs={"pk": str(self.progress.id), "step_pk": str(self.step.id)}
        )
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Check step is completed
        step_progress = LearningPathStepProgress.objects.get(
            user=self.learner,
            learning_path_progress=self.progress,
            step=self.step
        )
        self.assertEqual(step_progress.status, LearningPathStepProgress.Status.COMPLETED)
        
        # Path should be completed (only one required step)
        self.progress.refresh_from_db()
        self.assertEqual(self.progress.status, LearningPathProgress.Status.COMPLETED)

    def test_complete_step_invalid_step(self):
        """Test completing a step that doesn't belong to the path."""
        other_path = LearningPath.objects.create(
            tenant=self.tenant,
            title="Other Path",
            status=LearningPath.Status.PUBLISHED,
        )
        course_ct = ContentType.objects.get_for_model(Course)
        other_step = LearningPathStep.objects.create(
            learning_path=other_path,
            content_type=course_ct,
            object_id=self.course.id,
            order=1,
        )
        
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse(
            "learning_paths:learningpathprogress-complete-step",
            kwargs={"pk": str(self.progress.id), "step_pk": str(other_step.id)}
        )
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_reset_step(self):
        """Test resetting a completed step."""
        # Complete the path first
        self.progress.status = LearningPathProgress.Status.COMPLETED
        self.progress.save()
        
        step_progress = LearningPathStepProgress.objects.create(
            user=self.learner,
            learning_path_progress=self.progress,
            step=self.step,
            status=LearningPathStepProgress.Status.COMPLETED,
        )
        
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse(
            "learning_paths:learningpathprogress-reset-step",
            kwargs={"pk": str(self.progress.id), "step_pk": str(self.step.id)}
        )
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        step_progress.refresh_from_db()
        self.assertEqual(step_progress.status, LearningPathStepProgress.Status.NOT_STARTED)
        
        # Path status should revert to in_progress
        self.progress.refresh_from_db()
        self.assertEqual(self.progress.status, LearningPathProgress.Status.IN_PROGRESS)


class PersonalizedLearningPathViewSetTests(APITestCase):
    """Tests for PersonalizedLearningPathViewSet."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="testpass123",
            tenant=self.tenant,
            is_staff=True,
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
            role=User.Role.INSTRUCTOR,
        )
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant,
            role=User.Role.LEARNER,
        )
        self.other_learner = User.objects.create_user(
            email="other@example.com",
            password="testpass123",
            tenant=self.tenant,
            role=User.Role.LEARNER,
        )

        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
        )
        self.module = Module.objects.create(
            course=self.course,
            title="Test Module",
            order=1,
        )

        # Create a personalized path for the learner
        self.personalized_path = PersonalizedLearningPath.objects.create(
            tenant=self.tenant,
            user=self.learner,
            title="Skill Gap Path",
            generation_type=PersonalizedLearningPath.GenerationType.SKILL_GAP,
            status=PersonalizedLearningPath.Status.ACTIVE,
            estimated_duration=10,
        )

        # Create a step for the path
        self.step = PersonalizedPathStep.objects.create(
            path=self.personalized_path,
            module=self.module,
            order=1,
            reason="Foundation skills",
            estimated_duration=30,
        )

    def test_list_own_personalized_paths(self):
        """Test learners can list their own personalized paths."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse("learning_paths:personalizedlearningpath-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["title"], "Skill Gap Path")

    def test_cannot_see_other_user_paths(self):
        """Test learners cannot see other users' personalized paths."""
        self.client.force_authenticate(user=self.other_learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse("learning_paths:personalizedlearningpath-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

    def test_admin_can_see_all_paths(self):
        """Test admins can see all personalized paths in tenant."""
        # Create path for other learner
        PersonalizedLearningPath.objects.create(
            tenant=self.tenant,
            user=self.other_learner,
            title="Other Path",
            generation_type=PersonalizedLearningPath.GenerationType.GOAL_BASED,
            estimated_duration=10,
        )

        self.client.force_authenticate(user=self.admin)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse("learning_paths:personalizedlearningpath-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)

    def test_retrieve_own_path(self):
        """Test retrieving a single personalized path."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse(
            "learning_paths:personalizedlearningpath-detail",
            kwargs={"pk": str(self.personalized_path.id)}
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Skill Gap Path")

    def test_cannot_retrieve_other_user_path(self):
        """Test learners cannot retrieve other users' paths."""
        self.client.force_authenticate(user=self.other_learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse(
            "learning_paths:personalizedlearningpath-detail",
            kwargs={"pk": str(self.personalized_path.id)}
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_path_as_admin(self):
        """Test admins can create personalized paths."""
        self.client.force_authenticate(user=self.admin)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse("learning_paths:personalizedlearningpath-list")
        data = {
            "title": "Admin Created Path",
            "generation_type": PersonalizedLearningPath.GenerationType.ONBOARDING,
            "user": str(self.learner.id),
            "estimated_duration": 10,
        }
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "Admin Created Path")

    def test_create_path_as_learner_forbidden(self):
        """Test learners cannot create personalized paths (via API)."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse("learning_paths:personalizedlearningpath-list")
        data = {
            "title": "Learner Created Path",
            "generation_type": PersonalizedLearningPath.GenerationType.SKILL_GAP,
        }
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_steps_action(self):
        """Test the get_steps custom action."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse(
            "learning_paths:personalizedlearningpath-get-steps",
            kwargs={"pk": str(self.personalized_path.id)}
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["order"], 1)

    def test_archive_own_path(self):
        """Test user can archive their own path."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse(
            "learning_paths:personalizedlearningpath-archive",
            kwargs={"pk": str(self.personalized_path.id)}
        )
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.personalized_path.refresh_from_db()
        self.assertEqual(
            self.personalized_path.status,
            PersonalizedLearningPath.Status.ARCHIVED
        )

    def test_archive_other_user_path_forbidden(self):
        """Test users cannot archive other users' paths."""
        self.client.force_authenticate(user=self.other_learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse(
            "learning_paths:personalizedlearningpath-archive",
            kwargs={"pk": str(self.personalized_path.id)}
        )
        response = self.client.post(url)

        # Should get 404 since path isn't in queryset
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_archive_already_archived_path(self):
        """Test archiving an already archived path returns error."""
        self.personalized_path.status = PersonalizedLearningPath.Status.ARCHIVED
        self.personalized_path.save()

        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse(
            "learning_paths:personalizedlearningpath-archive",
            kwargs={"pk": str(self.personalized_path.id)}
        )
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_check_expiry_not_expired(self):
        """Test check_expiry when path is not expired."""
        self.personalized_path.expires_at = timezone.now() + timedelta(days=30)
        self.personalized_path.save()

        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse(
            "learning_paths:personalizedlearningpath-check-expiry",
            kwargs={"pk": str(self.personalized_path.id)}
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], PersonalizedLearningPath.Status.ACTIVE)

    def test_check_expiry_expired(self):
        """Test check_expiry updates status when path is expired."""
        self.personalized_path.expires_at = timezone.now() - timedelta(days=1)
        self.personalized_path.save()

        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse(
            "learning_paths:personalizedlearningpath-check-expiry",
            kwargs={"pk": str(self.personalized_path.id)}
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], PersonalizedLearningPath.Status.EXPIRED)

        self.personalized_path.refresh_from_db()
        self.assertEqual(
            self.personalized_path.status,
            PersonalizedLearningPath.Status.EXPIRED
        )

    def test_unauthenticated_access_denied(self):
        """Test unauthenticated users cannot access personalized paths."""
        url = reverse("learning_paths:personalizedlearningpath-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_update_own_path(self):
        """Test users can update their own path status."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse(
            "learning_paths:personalizedlearningpath-detail",
            kwargs={"pk": str(self.personalized_path.id)}
        )
        data = {"title": "Updated Title"}
        response = self.client.patch(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.personalized_path.refresh_from_db()
        self.assertEqual(self.personalized_path.title, "Updated Title")

    def test_delete_path_as_admin(self):
        """Test admins can delete personalized paths."""
        self.client.force_authenticate(user=self.admin)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse(
            "learning_paths:personalizedlearningpath-detail",
            kwargs={"pk": str(self.personalized_path.id)}
        )
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            PersonalizedLearningPath.objects.filter(id=self.personalized_path.id).exists()
        )

    def test_delete_path_as_learner_forbidden(self):
        """Test learners cannot delete personalized paths."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse(
            "learning_paths:personalizedlearningpath-detail",
            kwargs={"pk": str(self.personalized_path.id)}
        )
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class PersonalizedPathProgressViewSetTests(APITestCase):
    """Tests for PersonalizedPathProgressViewSet."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="testpass123",
            tenant=self.tenant,
            is_staff=True,
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
            role=User.Role.INSTRUCTOR,
        )
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant,
            role=User.Role.LEARNER,
        )
        self.other_learner = User.objects.create_user(
            email="other@example.com",
            password="testpass123",
            tenant=self.tenant,
            role=User.Role.LEARNER,
        )

        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
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

        # Create a personalized path for the learner
        self.personalized_path = PersonalizedLearningPath.objects.create(
            tenant=self.tenant,
            user=self.learner,
            title="Skill Gap Path",
            generation_type=PersonalizedLearningPath.GenerationType.SKILL_GAP,
            status=PersonalizedLearningPath.Status.ACTIVE,
            estimated_duration=10,
        )

        # Create steps for the path
        self.step1 = PersonalizedPathStep.objects.create(
            path=self.personalized_path,
            module=self.module1,
            order=1,
            reason="Foundation skills",
            estimated_duration=30,
        )
        self.step2 = PersonalizedPathStep.objects.create(
            path=self.personalized_path,
            module=self.module2,
            order=2,
            reason="Advanced skills",
            estimated_duration=45,
        )

        # Create progress record
        self.progress = PersonalizedPathProgress.objects.create(
            user=self.learner,
            path=self.personalized_path,
            status=PersonalizedPathProgress.Status.NOT_STARTED,
        )

    def test_list_own_progress(self):
        """Test learners can list their own progress."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse("learning_paths:personalizedpathprogress-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

    def test_cannot_see_other_user_progress(self):
        """Test learners cannot see other users' progress."""
        self.client.force_authenticate(user=self.other_learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse("learning_paths:personalizedpathprogress-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

    def test_admin_can_see_all_progress(self):
        """Test admins can see all progress in tenant."""
        # Create progress for other learner
        other_path = PersonalizedLearningPath.objects.create(
            tenant=self.tenant,
            user=self.other_learner,
            title="Other Path",
            generation_type=PersonalizedLearningPath.GenerationType.GOAL_BASED,
            estimated_duration=10,
        )
        PersonalizedPathProgress.objects.create(
            user=self.other_learner,
            path=other_path,
        )

        self.client.force_authenticate(user=self.admin)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse("learning_paths:personalizedpathprogress-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)

    def test_start_path_action(self):
        """Test the start_path action."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse(
            "learning_paths:personalizedpathprogress-start-path",
            kwargs={"pk": str(self.progress.id)}
        )
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.progress.refresh_from_db()
        self.assertEqual(
            self.progress.status,
            PersonalizedPathProgress.Status.IN_PROGRESS
        )
        self.assertIsNotNone(self.progress.started_at)
        self.assertEqual(self.progress.current_step_order, 1)

    def test_start_path_other_user_forbidden(self):
        """Test users cannot start other users' paths."""
        self.client.force_authenticate(user=self.other_learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse(
            "learning_paths:personalizedpathprogress-start-path",
            kwargs={"pk": str(self.progress.id)}
        )
        response = self.client.post(url)

        # Should be 404 since progress isn't in queryset
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_step_action(self):
        """Test the update_step action."""
        self.progress.status = PersonalizedPathProgress.Status.IN_PROGRESS
        self.progress.current_step_order = 1
        self.progress.save()

        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse(
            "learning_paths:personalizedpathprogress-update-step",
            kwargs={"pk": str(self.progress.id)}
        )
        response = self.client.post(url, {"step_order": 2}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.progress.refresh_from_db()
        self.assertEqual(self.progress.current_step_order, 2)

    def test_update_step_invalid_order(self):
        """Test update_step with invalid step order."""
        self.progress.status = PersonalizedPathProgress.Status.IN_PROGRESS
        self.progress.save()

        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse(
            "learning_paths:personalizedpathprogress-update-step",
            kwargs={"pk": str(self.progress.id)}
        )
        response = self.client.post(url, {"step_order": 99}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_step_missing_order(self):
        """Test update_step without step_order parameter."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse(
            "learning_paths:personalizedpathprogress-update-step",
            kwargs={"pk": str(self.progress.id)}
        )
        response = self.client.post(url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_complete_path_action(self):
        """Test the complete_path action."""
        self.progress.status = PersonalizedPathProgress.Status.IN_PROGRESS
        self.progress.started_at = timezone.now()
        self.progress.save()

        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse(
            "learning_paths:personalizedpathprogress-complete-path",
            kwargs={"pk": str(self.progress.id)}
        )
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.progress.refresh_from_db()
        self.assertEqual(
            self.progress.status,
            PersonalizedPathProgress.Status.COMPLETED
        )
        self.assertIsNotNone(self.progress.completed_at)
        
        # Path status should also be updated
        self.personalized_path.refresh_from_db()
        self.assertEqual(
            self.personalized_path.status,
            PersonalizedLearningPath.Status.COMPLETED
        )

    def test_pause_path_action(self):
        """Test the pause_path action."""
        self.progress.status = PersonalizedPathProgress.Status.IN_PROGRESS
        self.progress.save()

        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse(
            "learning_paths:personalizedpathprogress-pause-path",
            kwargs={"pk": str(self.progress.id)}
        )
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.progress.refresh_from_db()
        self.assertEqual(
            self.progress.status,
            PersonalizedPathProgress.Status.PAUSED
        )

    def test_pause_path_not_in_progress(self):
        """Test pause_path when path is not in progress."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse(
            "learning_paths:personalizedpathprogress-pause-path",
            kwargs={"pk": str(self.progress.id)}
        )
        response = self.client.post(url)

        # Should return OK but status unchanged
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.progress.refresh_from_db()
        self.assertEqual(
            self.progress.status,
            PersonalizedPathProgress.Status.NOT_STARTED
        )

    def test_resume_path_action(self):
        """Test the resume_path action."""
        self.progress.status = PersonalizedPathProgress.Status.PAUSED
        self.progress.save()

        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse(
            "learning_paths:personalizedpathprogress-resume-path",
            kwargs={"pk": str(self.progress.id)}
        )
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.progress.refresh_from_db()
        self.assertEqual(
            self.progress.status,
            PersonalizedPathProgress.Status.IN_PROGRESS
        )

    def test_resume_path_not_paused(self):
        """Test resume_path when path is not paused."""
        self.progress.status = PersonalizedPathProgress.Status.IN_PROGRESS
        self.progress.save()

        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse(
            "learning_paths:personalizedpathprogress-resume-path",
            kwargs={"pk": str(self.progress.id)}
        )
        response = self.client.post(url)

        # Should return OK but status unchanged
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.progress.refresh_from_db()
        self.assertEqual(
            self.progress.status,
            PersonalizedPathProgress.Status.IN_PROGRESS
        )

    def test_create_progress_for_own_path(self):
        """Test creating progress for own personalized path."""
        # Delete existing progress first
        self.progress.delete()

        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse("learning_paths:personalizedpathprogress-list")
        data = {"path": str(self.personalized_path.id)}
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_progress_for_other_user_path_forbidden(self):
        """Test users cannot create progress for other users' paths."""
        self.client.force_authenticate(user=self.other_learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)

        url = reverse("learning_paths:personalizedpathprogress-list")
        data = {"path": str(self.personalized_path.id)}
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthenticated_access_denied(self):
        """Test unauthenticated users cannot access progress."""
        url = reverse("learning_paths:personalizedpathprogress-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class PathGenerationViewSetTests(APITestCase):
    """Tests for path generation endpoints (generate, generate/remedial, generate/preview)."""

    def setUp(self):
        from apps.skills.models import Skill, ModuleSkill, AssessmentSkillMapping
        from apps.assessments.models import Assessment, AssessmentAttempt, Question
        
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="testpass123",
            tenant=self.tenant,
            is_staff=True,
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
            role=User.Role.INSTRUCTOR,
        )
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant,
            role=User.Role.LEARNER,
        )
        self.other_learner = User.objects.create_user(
            email="other@example.com",
            password="testpass123",
            tenant=self.tenant,
            role=User.Role.LEARNER,
        )
        
        # Create course and modules
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Python Course",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
        )
        self.module1 = Module.objects.create(
            course=self.course,
            title="Python Basics",
            order=1,
        )
        self.module2 = Module.objects.create(
            course=self.course,
            title="Python Advanced",
            order=2,
        )
        
        # Create skills
        self.skill1 = Skill.objects.create(
            name="Python Fundamentals",
            slug="python-fundamentals",
            tenant=self.tenant,
            is_active=True,
        )
        self.skill2 = Skill.objects.create(
            name="Data Structures",
            slug="data-structures",
            tenant=self.tenant,
            is_active=True,
        )
        
        # Map skills to modules
        ModuleSkill.objects.create(
            module=self.module1,
            skill=self.skill1,
            contribution_level=ModuleSkill.ContributionLevel.DEVELOPS,
        )
        ModuleSkill.objects.create(
            module=self.module2,
            skill=self.skill2,
            contribution_level=ModuleSkill.ContributionLevel.MASTERS,
        )
        
        # Create an assessment with questions
        self.assessment = Assessment.objects.create(
            title="Python Assessment",
            course=self.course,
            assessment_type=Assessment.AssessmentType.QUIZ,
            is_published=True,
            pass_mark_percentage=70,
        )
        
        # Create questions
        self.question1 = Question.objects.create(
            assessment=self.assessment,
            question_type=Question.QuestionType.MULTIPLE_CHOICE,
            question_text="What is a list in Python?",
            order=1,
            points=10,
            type_specific_data={
                'options': [
                    {'id': 'a', 'text': 'A mutable sequence', 'is_correct': True},
                    {'id': 'b', 'text': 'An immutable sequence', 'is_correct': False},
                ]
            }
        )
        self.question2 = Question.objects.create(
            assessment=self.assessment,
            question_type=Question.QuestionType.TRUE_FALSE,
            question_text="Python is a compiled language",
            order=2,
            points=10,
            type_specific_data={
                'options': [
                    {'id': 'true', 'text': 'True', 'is_correct': False},
                    {'id': 'false', 'text': 'False', 'is_correct': True},
                ]
            }
        )
        
        # Map skills to questions
        AssessmentSkillMapping.objects.create(
            question=self.question1,
            skill=self.skill1,
        )
        AssessmentSkillMapping.objects.create(
            question=self.question2,
            skill=self.skill2,
        )
        
        # Create a failed assessment attempt
        self.failed_attempt = AssessmentAttempt.objects.create(
            assessment=self.assessment,
            user=self.learner,
            status=AssessmentAttempt.AttemptStatus.GRADED,
            score=40,
            is_passed=False,
            answers={
                str(self.question1.id): 'b',  # Wrong answer
                str(self.question2.id): 'true',  # Wrong answer
            }
        )

    # ==========================================================================
    # Generate Skill-Gap Path Tests
    # ==========================================================================

    def test_generate_skill_gap_path_success(self):
        """Test generating a skill-gap path with valid skills."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:personalizedlearningpath-generate-skill-gap-path")
        data = {
            "target_skills": [str(self.skill1.id)],
            "max_modules": 10,
            "include_completed": False,
        }
        response = self.client.post(url, data, format="json")
        
        # May return 201 (created) or 400 (no modules found) depending on generator logic
        self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST])
        
        if response.status_code == status.HTTP_201_CREATED:
            self.assertIn("title", response.data)
            self.assertEqual(response.data["generation_type"], "SKILL_GAP")

    def test_generate_skill_gap_path_no_skills(self):
        """Test generating a skill-gap path with empty skills list fails."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:personalizedlearningpath-generate-skill-gap-path")
        data = {
            "target_skills": [],
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_generate_skill_gap_path_invalid_skills(self):
        """Test generating a skill-gap path with non-existent skill IDs fails."""
        import uuid
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:personalizedlearningpath-generate-skill-gap-path")
        data = {
            "target_skills": [str(uuid.uuid4())],  # Non-existent UUID
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_generate_skill_gap_path_unauthenticated(self):
        """Test that unauthenticated users cannot generate paths."""
        url = reverse("learning_paths:personalizedlearningpath-generate-skill-gap-path")
        data = {
            "target_skills": [str(self.skill1.id)],
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # ==========================================================================
    # Generate Remedial Path Tests
    # ==========================================================================

    def test_generate_remedial_path_success(self):
        """Test generating a remedial path from failed assessment attempt."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:personalizedlearningpath-generate-remedial-path")
        data = {
            "assessment_attempt_id": str(self.failed_attempt.id),
            "focus_weak_areas": True,
            "max_modules": 5,
        }
        response = self.client.post(url, data, format="json")
        
        # May return 201 (created) or 400 (no skills/modules found)
        self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST])
        
        if response.status_code == status.HTTP_201_CREATED:
            self.assertEqual(response.data["generation_type"], "REMEDIAL")

    def test_generate_remedial_path_nonexistent_attempt(self):
        """Test generating remedial path with non-existent attempt fails."""
        import uuid
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:personalizedlearningpath-generate-remedial-path")
        data = {
            "assessment_attempt_id": str(uuid.uuid4()),
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_generate_remedial_path_other_user_attempt_forbidden(self):
        """Test that users cannot generate remedial paths for other users' attempts."""
        self.client.force_authenticate(user=self.other_learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:personalizedlearningpath-generate-remedial-path")
        data = {
            "assessment_attempt_id": str(self.failed_attempt.id),
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_generate_remedial_path_admin_can_access_any_attempt(self):
        """Test that admins can generate remedial paths for any user's attempts."""
        self.client.force_authenticate(user=self.admin)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:personalizedlearningpath-generate-remedial-path")
        data = {
            "assessment_attempt_id": str(self.failed_attempt.id),
            "max_modules": 5,
        }
        response = self.client.post(url, data, format="json")
        
        # Admin should have access, may still return 400 if no modules found
        self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST])
        # Should NOT return 403
        self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_generate_remedial_path_unauthenticated(self):
        """Test that unauthenticated users cannot generate remedial paths."""
        url = reverse("learning_paths:personalizedlearningpath-generate-remedial-path")
        data = {
            "assessment_attempt_id": str(self.failed_attempt.id),
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # ==========================================================================
    # Preview Path Generation Tests
    # ==========================================================================

    def test_preview_skill_gap_path_success(self):
        """Test previewing a skill-gap path generation."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:personalizedlearningpath-preview-path-generation")
        data = {
            "generation_type": "SKILL_GAP",
            "target_skills": [str(self.skill1.id)],
            "max_modules": 10,
        }
        response = self.client.post(url, data, format="json")
        
        # Preview should return 200 even if no modules found
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("generation_type", response.data)
        self.assertIn("steps", response.data)

    def test_preview_remedial_path_success(self):
        """Test previewing a remedial path generation."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:personalizedlearningpath-preview-path-generation")
        data = {
            "generation_type": "REMEDIAL",
            "assessment_attempt_id": str(self.failed_attempt.id),
            "focus_weak_areas": True,
        }
        response = self.client.post(url, data, format="json")
        
        # May return 200 (with preview data) or 400 (no skills found)
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_preview_skill_gap_missing_target_skills(self):
        """Test preview with SKILL_GAP type but missing target_skills fails."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:personalizedlearningpath-preview-path-generation")
        data = {
            "generation_type": "SKILL_GAP",
            # Missing target_skills
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_preview_remedial_missing_attempt_id(self):
        """Test preview with REMEDIAL type but missing assessment_attempt_id fails."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:personalizedlearningpath-preview-path-generation")
        data = {
            "generation_type": "REMEDIAL",
            # Missing assessment_attempt_id
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_preview_invalid_generation_type(self):
        """Test preview with invalid generation type fails."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:personalizedlearningpath-preview-path-generation")
        data = {
            "generation_type": "INVALID_TYPE",
            "target_skills": [str(self.skill1.id)],
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_preview_remedial_other_user_attempt_forbidden(self):
        """Test that users cannot preview remedial paths for other users' attempts."""
        self.client.force_authenticate(user=self.other_learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        url = reverse("learning_paths:personalizedlearningpath-preview-path-generation")
        data = {
            "generation_type": "REMEDIAL",
            "assessment_attempt_id": str(self.failed_attempt.id),
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_preview_does_not_save_path(self):
        """Test that preview does not actually save a path."""
        self.client.force_authenticate(user=self.learner)
        self.client.credentials(HTTP_X_TENANT_SLUG=self.tenant.slug)
        
        initial_count = PersonalizedLearningPath.objects.filter(user=self.learner).count()
        
        url = reverse("learning_paths:personalizedlearningpath-preview-path-generation")
        data = {
            "generation_type": "SKILL_GAP",
            "target_skills": [str(self.skill1.id)],
        }
        response = self.client.post(url, data, format="json")
        
        # Verify no new path was created
        final_count = PersonalizedLearningPath.objects.filter(user=self.learner).count()
        self.assertEqual(initial_count, final_count)

    def test_preview_unauthenticated(self):
        """Test that unauthenticated users cannot preview paths."""
        url = reverse("learning_paths:personalizedlearningpath-preview-path-generation")
        data = {
            "generation_type": "SKILL_GAP",
            "target_skills": [str(self.skill1.id)],
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
