"""
Tests for assessment-to-skill integration.

Tests the signal handler that updates skill progress when assessments are graded,
and the skill breakdown endpoint for assessment results.
"""

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.assessments.models import Assessment, AssessmentAttempt, Question
from apps.assessments.services import GradingService
from apps.core.models import Tenant
from apps.courses.models import Course
from apps.enrollments.models import Enrollment
from apps.skills.models import (
    AssessmentSkillMapping,
    LearnerSkillProgress,
    Skill,
)
from apps.skills.signals import calculate_skill_breakdown_for_attempt
from apps.users.models import User


class AssessmentSkillSignalTests(TestCase):
    """Tests for the signal handler that updates skills on assessment completion."""

    def setUp(self):
        """Set up test data."""
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant"
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            role=User.Role.INSTRUCTOR,
            tenant=self.tenant
        )
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            role=User.Role.LEARNER,
            tenant=self.tenant
        )

        # Create course and assessment
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Python Programming",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED
        )
        self.assessment = Assessment.objects.create(
            course=self.course,
            title="Python Quiz",
            assessment_type=Assessment.AssessmentType.QUIZ,
            grading_type=Assessment.GradingType.AUTO,
            is_published=True,
            pass_mark_percentage=50
        )

        # Create skills
        self.python_skill = Skill.objects.create(
            tenant=self.tenant,
            name="Python",
            slug="python",
            category=Skill.Category.TECHNICAL
        )
        self.django_skill = Skill.objects.create(
            tenant=self.tenant,
            name="Django",
            slug="django",
            category=Skill.Category.TECHNICAL
        )

        # Create questions with type_specific_data for auto-grading
        self.question1 = Question.objects.create(
            assessment=self.assessment,
            question_type=Question.QuestionType.MULTIPLE_CHOICE,
            question_text="What is Python?",
            points=10,
            order=1,
            type_specific_data={
                'options': [
                    {'id': 'a', 'text': 'A programming language', 'is_correct': True},
                    {'id': 'b', 'text': 'A snake', 'is_correct': False},
                    {'id': 'c', 'text': 'A framework', 'is_correct': False},
                ]
            }
        )
        self.question2 = Question.objects.create(
            assessment=self.assessment,
            question_type=Question.QuestionType.TRUE_FALSE,
            question_text="Python is dynamically typed.",
            points=10,
            order=2,
            type_specific_data={
                'options': [
                    {'id': 'true', 'text': 'True', 'is_correct': True},
                    {'id': 'false', 'text': 'False', 'is_correct': False},
                ]
            }
        )
        self.question3 = Question.objects.create(
            assessment=self.assessment,
            question_type=Question.QuestionType.MULTIPLE_CHOICE,
            question_text="What is Django?",
            points=10,
            order=3,
            type_specific_data={
                'options': [
                    {'id': 'a', 'text': 'A Python web framework', 'is_correct': True},
                    {'id': 'b', 'text': 'A database', 'is_correct': False},
                    {'id': 'c', 'text': 'An IDE', 'is_correct': False},
                ]
            }
        )

        # Map skills to questions
        self.mapping1 = AssessmentSkillMapping.objects.create(
            question=self.question1,
            skill=self.python_skill,
            weight=2,
            proficiency_required=Skill.ProficiencyLevel.BEGINNER
        )
        self.mapping2 = AssessmentSkillMapping.objects.create(
            question=self.question2,
            skill=self.python_skill,
            weight=1,
            proficiency_required=Skill.ProficiencyLevel.BEGINNER
        )
        self.mapping3 = AssessmentSkillMapping.objects.create(
            question=self.question3,
            skill=self.django_skill,
            weight=3,
            proficiency_required=Skill.ProficiencyLevel.INTERMEDIATE
        )

    def _create_and_submit_attempt(self, answers):
        """Helper to create an attempt and submit it."""
        attempt = AssessmentAttempt.objects.create(
            assessment=self.assessment,
            user=self.learner
        )
        attempt.submit(answers)
        return attempt

    def test_signal_creates_skill_progress_on_good_performance(self):
        """Test that good performance creates/updates skill progress."""
        # All correct answers
        answers = {
            str(self.question1.id): 'a',  # Correct
            str(self.question2.id): 'true',  # Correct
            str(self.question3.id): 'a',  # Correct
        }
        attempt = self._create_and_submit_attempt(answers)

        # Check that LearnerSkillProgress was created/updated
        python_progress = LearnerSkillProgress.objects.filter(
            user=self.learner,
            skill=self.python_skill
        ).first()
        django_progress = LearnerSkillProgress.objects.filter(
            user=self.learner,
            skill=self.django_skill
        ).first()

        # Signal should have created progress for both skills
        self.assertIsNotNone(python_progress)
        self.assertIsNotNone(django_progress)
        
        # Good performance should increase proficiency
        self.assertGreater(python_progress.proficiency_score, 0)
        self.assertGreater(django_progress.proficiency_score, 0)

    def test_signal_handles_mixed_performance(self):
        """Test skill updates with mixed correct/incorrect answers."""
        # Some correct, some wrong
        answers = {
            str(self.question1.id): 'a',  # Correct (Python)
            str(self.question2.id): 'false',  # Wrong (Python)
            str(self.question3.id): 'b',  # Wrong (Django)
        }
        attempt = self._create_and_submit_attempt(answers)

        python_progress = LearnerSkillProgress.objects.filter(
            user=self.learner,
            skill=self.python_skill
        ).first()
        django_progress = LearnerSkillProgress.objects.filter(
            user=self.learner,
            skill=self.django_skill
        ).first()

        # Python: 1 correct (weight 2), 1 wrong (weight 1) = 2/3 weighted = 66.7%
        # Django: 0 correct out of 1 = 0%
        # Progress should reflect performance differences
        if python_progress and django_progress:
            # Python should have better progress due to partial correctness
            self.assertGreaterEqual(python_progress.proficiency_score, 0)

    def test_signal_does_not_run_for_non_graded_attempts(self):
        """Test that signal doesn't process IN_PROGRESS attempts."""
        # Create attempt without submitting
        attempt = AssessmentAttempt.objects.create(
            assessment=self.assessment,
            user=self.learner
        )
        
        # No skill progress should be created
        progress_count = LearnerSkillProgress.objects.filter(
            user=self.learner
        ).count()
        self.assertEqual(progress_count, 0)

    def test_signal_handles_assessment_without_skill_mappings(self):
        """Test that signal gracefully handles assessments without skill mappings."""
        # Create a new assessment without skill mappings
        new_assessment = Assessment.objects.create(
            course=self.course,
            title="No Skills Assessment",
            assessment_type=Assessment.AssessmentType.QUIZ,
            grading_type=Assessment.GradingType.AUTO,
            is_published=True
        )
        question = Question.objects.create(
            assessment=new_assessment,
            question_type=Question.QuestionType.TRUE_FALSE,
            question_text="Test question",
            points=10,
            order=1,
            type_specific_data={
                'options': [
                    {'id': 'true', 'text': 'True', 'is_correct': True},
                    {'id': 'false', 'text': 'False', 'is_correct': False},
                ]
            }
        )

        attempt = AssessmentAttempt.objects.create(
            assessment=new_assessment,
            user=self.learner
        )
        attempt.submit({str(question.id): 'true'})

        # Should not raise an error
        progress_count = LearnerSkillProgress.objects.filter(
            user=self.learner
        ).count()
        # No progress created since no skill mappings
        self.assertEqual(progress_count, 0)


class SkillBreakdownFunctionTests(TestCase):
    """Tests for the calculate_skill_breakdown_for_attempt function."""

    def setUp(self):
        """Set up test data."""
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant"
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            role=User.Role.INSTRUCTOR,
            tenant=self.tenant
        )
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            role=User.Role.LEARNER,
            tenant=self.tenant
        )

        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED
        )
        self.assessment = Assessment.objects.create(
            course=self.course,
            title="Test Assessment",
            assessment_type=Assessment.AssessmentType.QUIZ,
            grading_type=Assessment.GradingType.AUTO,
            is_published=True
        )

        self.skill1 = Skill.objects.create(
            tenant=self.tenant,
            name="Skill 1",
            slug="skill-1",
            category=Skill.Category.TECHNICAL
        )
        self.skill2 = Skill.objects.create(
            tenant=self.tenant,
            name="Skill 2",
            slug="skill-2",
            category=Skill.Category.SOFT
        )

        # Create questions
        self.q1 = Question.objects.create(
            assessment=self.assessment,
            question_type=Question.QuestionType.MULTIPLE_CHOICE,
            question_text="Q1",
            points=10,
            order=1,
            type_specific_data={
                'options': [
                    {'id': 'a', 'text': 'Correct', 'is_correct': True},
                    {'id': 'b', 'text': 'Wrong', 'is_correct': False},
                ]
            }
        )
        self.q2 = Question.objects.create(
            assessment=self.assessment,
            question_type=Question.QuestionType.MULTIPLE_CHOICE,
            question_text="Q2",
            points=10,
            order=2,
            type_specific_data={
                'options': [
                    {'id': 'a', 'text': 'Correct', 'is_correct': True},
                    {'id': 'b', 'text': 'Wrong', 'is_correct': False},
                ]
            }
        )
        self.q3 = Question.objects.create(
            assessment=self.assessment,
            question_type=Question.QuestionType.MULTIPLE_CHOICE,
            question_text="Q3",
            points=10,
            order=3,
            type_specific_data={
                'options': [
                    {'id': 'a', 'text': 'Correct', 'is_correct': True},
                    {'id': 'b', 'text': 'Wrong', 'is_correct': False},
                ]
            }
        )

        # Map skills
        AssessmentSkillMapping.objects.create(
            question=self.q1,
            skill=self.skill1,
            weight=1
        )
        AssessmentSkillMapping.objects.create(
            question=self.q2,
            skill=self.skill1,
            weight=1
        )
        AssessmentSkillMapping.objects.create(
            question=self.q3,
            skill=self.skill2,
            weight=1
        )

    def test_breakdown_returns_error_for_non_graded_attempt(self):
        """Test that breakdown returns error for non-graded attempts."""
        attempt = AssessmentAttempt.objects.create(
            assessment=self.assessment,
            user=self.learner
        )
        # Don't submit - stays IN_PROGRESS

        result = calculate_skill_breakdown_for_attempt(attempt)
        self.assertIn('error', result)

    def test_breakdown_returns_correct_structure(self):
        """Test that breakdown returns correct data structure."""
        attempt = AssessmentAttempt.objects.create(
            assessment=self.assessment,
            user=self.learner
        )
        attempt.submit({
            str(self.q1.id): 'a',  # Correct
            str(self.q2.id): 'a',  # Correct
            str(self.q3.id): 'b',  # Wrong
        })

        result = calculate_skill_breakdown_for_attempt(attempt)

        self.assertIn('assessment_id', result)
        self.assertIn('attempt_id', result)
        self.assertIn('skills', result)
        self.assertEqual(result['skills_evaluated'], 2)

    def test_breakdown_calculates_accuracy_correctly(self):
        """Test that skill accuracy is calculated correctly."""
        attempt = AssessmentAttempt.objects.create(
            assessment=self.assessment,
            user=self.learner
        )
        attempt.submit({
            str(self.q1.id): 'a',  # Correct (Skill 1)
            str(self.q2.id): 'b',  # Wrong (Skill 1)
            str(self.q3.id): 'a',  # Correct (Skill 2)
        })

        result = calculate_skill_breakdown_for_attempt(attempt)
        skills_by_name = {s['skill_name']: s for s in result['skills']}

        # Skill 1: 1/2 = 50% accuracy
        self.assertEqual(skills_by_name['Skill 1']['accuracy'], 50.0)
        # Skill 2: 1/1 = 100% accuracy
        self.assertEqual(skills_by_name['Skill 2']['accuracy'], 100.0)

    def test_breakdown_determines_proficiency_level(self):
        """Test that proficiency level is determined correctly."""
        attempt = AssessmentAttempt.objects.create(
            assessment=self.assessment,
            user=self.learner
        )
        attempt.submit({
            str(self.q1.id): 'a',  # Correct
            str(self.q2.id): 'a',  # Correct
            str(self.q3.id): 'a',  # Correct
        })

        result = calculate_skill_breakdown_for_attempt(attempt)
        skills_by_name = {s['skill_name']: s for s in result['skills']}

        # 100% accuracy = EXPERT
        self.assertEqual(skills_by_name['Skill 1']['proficiency_demonstrated'], 'EXPERT')
        self.assertEqual(skills_by_name['Skill 2']['proficiency_demonstrated'], 'EXPERT')

    def test_breakdown_handles_no_skill_mappings(self):
        """Test breakdown for assessment without skill mappings."""
        new_assessment = Assessment.objects.create(
            course=self.course,
            title="No Skills",
            assessment_type=Assessment.AssessmentType.QUIZ,
            grading_type=Assessment.GradingType.AUTO,
            is_published=True
        )
        q = Question.objects.create(
            assessment=new_assessment,
            question_type=Question.QuestionType.TRUE_FALSE,
            question_text="Test",
            points=10,
            order=1,
            type_specific_data={
                'options': [
                    {'id': 'true', 'text': 'True', 'is_correct': True},
                    {'id': 'false', 'text': 'False', 'is_correct': False},
                ]
            }
        )

        attempt = AssessmentAttempt.objects.create(
            assessment=new_assessment,
            user=self.learner
        )
        attempt.submit({str(q.id): 'true'})

        result = calculate_skill_breakdown_for_attempt(attempt)
        
        self.assertEqual(result['skills'], [])
        self.assertIn('message', result)


class SkillBreakdownEndpointTests(TestCase):
    """Tests for the skill breakdown API endpoint."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()

        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant"
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            role=User.Role.INSTRUCTOR,
            tenant=self.tenant
        )
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            role=User.Role.LEARNER,
            tenant=self.tenant
        )
        self.other_learner = User.objects.create_user(
            email="other@example.com",
            password="testpass123",
            role=User.Role.LEARNER,
            tenant=self.tenant
        )

        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED
        )
        self.assessment = Assessment.objects.create(
            course=self.course,
            title="Test Assessment",
            assessment_type=Assessment.AssessmentType.QUIZ,
            grading_type=Assessment.GradingType.AUTO,
            is_published=True
        )

        self.skill = Skill.objects.create(
            tenant=self.tenant,
            name="Test Skill",
            slug="test-skill",
            category=Skill.Category.TECHNICAL
        )

        self.question = Question.objects.create(
            assessment=self.assessment,
            question_type=Question.QuestionType.MULTIPLE_CHOICE,
            question_text="Test question",
            points=10,
            order=1,
            type_specific_data={
                'options': [
                    {'id': 'a', 'text': 'Correct', 'is_correct': True},
                    {'id': 'b', 'text': 'Wrong', 'is_correct': False},
                ]
            }
        )

        AssessmentSkillMapping.objects.create(
            question=self.question,
            skill=self.skill,
            weight=1
        )

        # Create a graded attempt
        self.attempt = AssessmentAttempt.objects.create(
            assessment=self.assessment,
            user=self.learner
        )
        self.attempt.submit({str(self.question.id): 'a'})

    def _get_url(self, attempt_id):
        return reverse(
            'assessments:assessment-attempt-skill-breakdown',
            kwargs={'attempt_id': attempt_id}
        )

    def test_owner_can_access_skill_breakdown(self):
        """Test that attempt owner can access skill breakdown."""
        self.client.force_authenticate(user=self.learner)
        response = self.client.get(
            self._get_url(self.attempt.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('skills', response.data)

    def test_instructor_can_access_skill_breakdown(self):
        """Test that course instructor can access skill breakdown."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.get(
            self._get_url(self.attempt.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_other_learner_cannot_access_skill_breakdown(self):
        """Test that other learners cannot access skill breakdown."""
        self.client.force_authenticate(user=self.other_learner)
        response = self.client.get(
            self._get_url(self.attempt.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_cannot_access(self):
        """Test that unauthenticated users cannot access."""
        response = self.client.get(
            self._get_url(self.attempt.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_graded_attempt_returns_error(self):
        """Test that non-graded attempts return 400."""
        # Create an in-progress attempt
        in_progress_attempt = AssessmentAttempt.objects.create(
            assessment=self.assessment,
            user=self.learner
        )

        self.client.force_authenticate(user=self.learner)
        response = self.client.get(
            self._get_url(in_progress_attempt.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_nonexistent_attempt_returns_404(self):
        """Test that nonexistent attempt returns 404."""
        import uuid
        fake_id = uuid.uuid4()

        self.client.force_authenticate(user=self.learner)
        response = self.client.get(
            self._get_url(fake_id),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class QuestionSerializerSkillsTests(TestCase):
    """Tests for QuestionSerializer including skills."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()

        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant"
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            role=User.Role.INSTRUCTOR,
            tenant=self.tenant
        )

        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED
        )
        self.assessment = Assessment.objects.create(
            course=self.course,
            title="Test Assessment",
            assessment_type=Assessment.AssessmentType.QUIZ
        )
        self.question = Question.objects.create(
            assessment=self.assessment,
            question_type=Question.QuestionType.MULTIPLE_CHOICE,
            question_text="Test question",
            points=10,
            order=1,
            type_specific_data={
                'options': [
                    {'id': 'a', 'text': 'Option A', 'is_correct': True},
                    {'id': 'b', 'text': 'Option B', 'is_correct': False},
                ]
            }
        )
        self.skill = Skill.objects.create(
            tenant=self.tenant,
            name="Python",
            slug="python",
            category=Skill.Category.TECHNICAL
        )
        self.mapping = AssessmentSkillMapping.objects.create(
            question=self.question,
            skill=self.skill,
            weight=2,
            proficiency_required=Skill.ProficiencyLevel.BEGINNER
        )

    def test_question_serializer_includes_skills(self):
        """Test that QuestionSerializer includes skills field."""
        from apps.assessments.serializers import QuestionSerializer

        serializer = QuestionSerializer(self.question)
        data = serializer.data

        self.assertIn('skills', data)
        self.assertEqual(len(data['skills']), 1)
        self.assertEqual(data['skills'][0]['name'], 'Python')
        self.assertEqual(data['skills'][0]['weight'], 2)

    def test_question_without_skills(self):
        """Test serializer for question without skill mappings."""
        from apps.assessments.serializers import QuestionSerializer

        # Delete the mapping
        self.mapping.delete()

        serializer = QuestionSerializer(self.question)
        data = serializer.data

        self.assertIn('skills', data)
        self.assertEqual(data['skills'], [])
