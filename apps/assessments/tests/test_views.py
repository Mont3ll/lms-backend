"""
Tests for Assessment views and viewsets.
Tests cover permission checks, enrollment requirements, and assessment attempts.
"""

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from apps.core.models import Tenant
from apps.users.models import User
from apps.courses.models import Course
from apps.enrollments.models import Enrollment
from apps.assessments.models import Assessment, AssessmentAttempt, Question


class AssessmentTestCase(APITestCase):
    """Base test case with common setup for assessment tests."""

    def setUp(self):
        """Set up test data."""
        # Create tenant
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant",
        )
        
        # Create users
        self.admin_user = User.objects.create_user(
            email="admin@test.com",
            password="testpass123",
            first_name="Admin",
            last_name="User",
            role=User.Role.ADMIN,
            tenant=self.tenant,
            is_staff=True,
            status=User.Status.ACTIVE,
        )
        
        self.instructor_user = User.objects.create_user(
            email="instructor@test.com",
            password="testpass123",
            first_name="Instructor",
            last_name="User",
            role=User.Role.INSTRUCTOR,
            tenant=self.tenant,
            status=User.Status.ACTIVE,
        )
        
        self.learner_user = User.objects.create_user(
            email="learner@test.com",
            password="testpass123",
            first_name="Learner",
            last_name="User",
            role=User.Role.LEARNER,
            tenant=self.tenant,
            status=User.Status.ACTIVE,
        )
        
        self.other_learner = User.objects.create_user(
            email="other_learner@test.com",
            password="testpass123",
            first_name="Other",
            last_name="Learner",
            role=User.Role.LEARNER,
            tenant=self.tenant,
            status=User.Status.ACTIVE,
        )
        
        # Create course
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            slug="test-course",
            instructor=self.instructor_user,
            status=Course.Status.PUBLISHED,
        )
        
        # Create assessment
        self.assessment = Assessment.objects.create(
            course=self.course,
            title="Test Assessment",
            assessment_type=Assessment.AssessmentType.QUIZ,
            grading_type=Assessment.GradingType.AUTO,
            max_attempts=3,
            pass_mark_percentage=50,
            is_published=True,
        )
        
        # Create questions
        self.question = Question.objects.create(
            assessment=self.assessment,
            question_text="What is 2 + 2?",
            question_type=Question.QuestionType.MULTIPLE_CHOICE,
            order=1,
            points=10,
            type_specific_data={
                'options': [
                    {'id': 'opt1', 'text': '3', 'is_correct': False},
                    {'id': 'opt2', 'text': '4', 'is_correct': True},
                    {'id': 'opt3', 'text': '5', 'is_correct': False},
                ],
                'allow_multiple': False
            }
        )
        
        # Create enrollment for learner
        self.enrollment = Enrollment.objects.create(
            user=self.learner_user,
            course=self.course,
            status=Enrollment.Status.ACTIVE,
        )
        
        # Set up API client
        self.client = APIClient()


class StartAssessmentAttemptViewTests(AssessmentTestCase):
    """Tests for StartAssessmentAttemptView."""

    def test_start_attempt_requires_authentication(self):
        """Test that unauthenticated users cannot start an attempt."""
        url = reverse('assessments:assessment-attempt-start', kwargs={'assessment_id': self.assessment.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_start_attempt_requires_learner_role(self):
        """Test that only learners can start an attempt."""
        self.client.force_authenticate(user=self.instructor_user)
        url = reverse('assessments:assessment-attempt-start', kwargs={'assessment_id': self.assessment.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_start_attempt_requires_enrollment(self):
        """Test that learner must be enrolled to start an attempt."""
        # Use learner without enrollment
        self.client.force_authenticate(user=self.other_learner)
        url = reverse('assessments:assessment-attempt-start', kwargs={'assessment_id': self.assessment.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("enrolled", response.data.get("detail", "").lower())

    def test_start_attempt_success(self):
        """Test successful attempt start for enrolled learner."""
        self.client.force_authenticate(user=self.learner_user)
        url = reverse('assessments:assessment-attempt-start', kwargs={'assessment_id': self.assessment.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("id", response.data)
        
        # Verify attempt created
        attempt = AssessmentAttempt.objects.get(id=response.data['id'])
        self.assertEqual(attempt.user, self.learner_user)
        self.assertEqual(attempt.assessment, self.assessment)
        self.assertEqual(attempt.status, AssessmentAttempt.AttemptStatus.IN_PROGRESS)

    def test_start_attempt_max_attempts_exceeded(self):
        """Test that user cannot exceed max attempts."""
        self.client.force_authenticate(user=self.learner_user)
        url = reverse('assessments:assessment-attempt-start', kwargs={'assessment_id': self.assessment.id})
        
        # Create max number of attempts
        for i in range(self.assessment.max_attempts):
            attempt = AssessmentAttempt.objects.create(
                assessment=self.assessment,
                user=self.learner_user,
                status=AssessmentAttempt.AttemptStatus.SUBMITTED,
            )
        
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("maximum", response.data.get("detail", "").lower())

    def test_start_attempt_past_due_date(self):
        """Test that user cannot start attempt after due date."""
        self.assessment.due_date = timezone.now() - timezone.timedelta(days=1)
        self.assessment.save()
        
        self.client.force_authenticate(user=self.learner_user)
        url = reverse('assessments:assessment-attempt-start', kwargs={'assessment_id': self.assessment.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("due date", response.data.get("detail", "").lower())

    def test_start_attempt_in_progress_conflict(self):
        """Test that user cannot start new attempt while one is in progress."""
        # Create in-progress attempt
        existing_attempt = AssessmentAttempt.objects.create(
            assessment=self.assessment,
            user=self.learner_user,
            status=AssessmentAttempt.AttemptStatus.IN_PROGRESS,
        )
        
        self.client.force_authenticate(user=self.learner_user)
        url = reverse('assessments:assessment-attempt-start', kwargs={'assessment_id': self.assessment.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        # Verify existing attempt data is returned for frontend to resume
        self.assertIn("existing_attempt", response.data)
        self.assertEqual(response.data["existing_attempt"]["attempt_id"], str(existing_attempt.id))

    def test_start_attempt_expired_attempt_auto_submits_and_allows_new(self):
        """Test that expired in-progress attempt is auto-submitted and new attempt can be created."""
        from datetime import timedelta
        from django.utils import timezone
        
        # Set time limit on assessment
        self.assessment.time_limit_minutes = 30
        self.assessment.max_attempts = 3
        self.assessment.save()
        
        # Create in-progress attempt
        existing_attempt = AssessmentAttempt.objects.create(
            assessment=self.assessment,
            user=self.learner_user,
            status=AssessmentAttempt.AttemptStatus.IN_PROGRESS,
        )
        # Manually set start_time to 2 hours ago (expired) - bypass auto_now_add
        expired_start_time = timezone.now() - timedelta(hours=2)
        AssessmentAttempt.objects.filter(pk=existing_attempt.pk).update(start_time=expired_start_time)
        
        self.client.force_authenticate(user=self.learner_user)
        url = reverse('assessments:assessment-attempt-start', kwargs={'assessment_id': self.assessment.id})
        response = self.client.post(url)
        
        # Should create a new attempt, not return 409
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Old attempt should be auto-submitted and graded
        existing_attempt.refresh_from_db()
        # After auto-submission, GradingService is called which grades the attempt
        self.assertEqual(existing_attempt.status, AssessmentAttempt.AttemptStatus.GRADED)
        self.assertIsNotNone(existing_attempt.end_time)

    def test_start_attempt_unpublished_assessment_404(self):
        """Test that unpublished assessment returns 404."""
        self.assessment.is_published = False
        self.assessment.save()
        
        self.client.force_authenticate(user=self.learner_user)
        url = reverse('assessments:assessment-attempt-start', kwargs={'assessment_id': self.assessment.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class AssessmentAttemptResultViewTests(AssessmentTestCase):
    """Tests for AssessmentAttemptResultView."""

    def setUp(self):
        super().setUp()
        # Create an attempt for learner
        self.attempt = AssessmentAttempt.objects.create(
            assessment=self.assessment,
            user=self.learner_user,
            status=AssessmentAttempt.AttemptStatus.SUBMITTED,
            score=80,
            is_passed=True,
        )

    def test_view_attempt_owner_can_access(self):
        """Test that attempt owner can view their attempt."""
        self.client.force_authenticate(user=self.learner_user)
        url = reverse('assessments:assessment-attempt-result', kwargs={'id': self.attempt.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.attempt.id))

    def test_view_attempt_instructor_can_access(self):
        """Test that course instructor can view any attempt."""
        self.client.force_authenticate(user=self.instructor_user)
        url = reverse('assessments:assessment-attempt-result', kwargs={'id': self.attempt.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_view_attempt_admin_can_access(self):
        """Test that admin can view any attempt."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('assessments:assessment-attempt-result', kwargs={'id': self.attempt.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_view_attempt_other_learner_denied(self):
        """Test that other learner cannot view someone else's attempt."""
        self.client.force_authenticate(user=self.other_learner)
        url = reverse('assessments:assessment-attempt-result', kwargs={'id': self.attempt.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class AssessmentViewSetTests(AssessmentTestCase):
    """Tests for AssessmentViewSet."""

    def test_attempts_endpoint_learner_sees_only_own_attempts(self):
        """Test that learner only sees their own attempts when fetching attempts for an assessment."""
        # Create attempts for both learners
        learner_attempt = AssessmentAttempt.objects.create(
            assessment=self.assessment,
            user=self.learner_user,
            status=AssessmentAttempt.AttemptStatus.SUBMITTED,
            score=80,
        )
        other_learner_attempt = AssessmentAttempt.objects.create(
            assessment=self.assessment,
            user=self.other_learner,
            status=AssessmentAttempt.AttemptStatus.SUBMITTED,
            score=70,
        )
        
        # As learner, should only see own attempt
        self.client.force_authenticate(user=self.learner_user)
        url = f'/api/v1/assessments/{self.assessment.id}/attempts/'
        response = self.client.get(url, HTTP_X_TENANT_SLUG='test-tenant')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], str(learner_attempt.id))
        
    def test_attempts_endpoint_instructor_sees_all_attempts(self):
        """Test that instructor sees all attempts when fetching attempts for an assessment."""
        # Create attempts for both learners
        learner_attempt = AssessmentAttempt.objects.create(
            assessment=self.assessment,
            user=self.learner_user,
            status=AssessmentAttempt.AttemptStatus.SUBMITTED,
            score=80,
        )
        other_learner_attempt = AssessmentAttempt.objects.create(
            assessment=self.assessment,
            user=self.other_learner,
            status=AssessmentAttempt.AttemptStatus.SUBMITTED,
            score=70,
        )
        
        # As instructor, should see all attempts
        self.client.force_authenticate(user=self.instructor_user)
        url = f'/api/v1/assessments/{self.assessment.id}/attempts/'
        response = self.client.get(url, HTTP_X_TENANT_SLUG='test-tenant')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_create_assessment_requires_instructor_or_admin(self):
        """Test that creating assessment requires instructor or admin role."""
        self.client.force_authenticate(user=self.learner_user)
        data = {
            'course': str(self.course.id),
            'title': 'New Assessment',
            'assessment_type': 'QUIZ',
        }
        response = self.client.post(
            '/api/v1/assessments/',
            data,
            format='json',
            HTTP_X_TENANT_SLUG='test-tenant'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_assessment_instructor_only_for_own_courses(self):
        """Test that instructor can only create assessments for courses they teach."""
        # Create another instructor
        other_instructor = User.objects.create_user(
            email="other_instructor@test.com",
            password="testpass123",
            first_name="Other",
            last_name="Instructor",
            role=User.Role.INSTRUCTOR,
            tenant=self.tenant,
            status=User.Status.ACTIVE,
        )
        
        self.client.force_authenticate(user=other_instructor)
        data = {
            'course': str(self.course.id),  # Course taught by self.instructor_user
            'title': 'New Assessment',
            'assessment_type': 'QUIZ',
        }
        response = self.client.post(
            '/api/v1/assessments/',
            data,
            format='json',
            HTTP_X_TENANT_SLUG='test-tenant'
        )
        # Should be denied - not the course instructor
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_400_BAD_REQUEST])


class SubmitAssessmentAttemptViewTests(AssessmentTestCase):
    """Tests for SubmitAssessmentAttemptView."""

    def setUp(self):
        super().setUp()
        # Create an in-progress attempt
        self.attempt = AssessmentAttempt.objects.create(
            assessment=self.assessment,
            user=self.learner_user,
            status=AssessmentAttempt.AttemptStatus.IN_PROGRESS,
        )

    def test_submit_requires_owner(self):
        """Test that only the attempt owner can submit."""
        self.client.force_authenticate(user=self.other_learner)
        url = reverse('assessments:assessment-attempt-submit', kwargs={'attempt_id': self.attempt.id})
        response = self.client.post(url, {'answers': {}}, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_submit_success(self):
        """Test successful submission."""
        self.client.force_authenticate(user=self.learner_user)
        url = reverse('assessments:assessment-attempt-submit', kwargs={'attempt_id': self.attempt.id})
        data = {
            'answers': {
                str(self.question.id): ['opt2']  # Correct answer
            }
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify attempt updated - auto-graded assessments go to GRADED status
        self.attempt.refresh_from_db()
        self.assertIn(
            self.attempt.status, 
            [AssessmentAttempt.AttemptStatus.SUBMITTED, AssessmentAttempt.AttemptStatus.GRADED]
        )

    def test_cannot_submit_already_submitted(self):
        """Test that already submitted attempt cannot be resubmitted."""
        self.attempt.status = AssessmentAttempt.AttemptStatus.SUBMITTED
        self.attempt.save()
        
        self.client.force_authenticate(user=self.learner_user)
        url = reverse('assessments:assessment-attempt-submit', kwargs={'attempt_id': self.attempt.id})
        response = self.client.post(url, {'answers': {}}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
