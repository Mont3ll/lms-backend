"""Tests for skills app viewsets."""

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.assessments.models import Assessment, Question
from apps.core.models import Tenant
from apps.courses.models import Course, Module
from apps.skills.models import (
    AssessmentSkillMapping,
    LearnerSkillProgress,
    ModuleSkill,
    Skill,
)
from apps.users.models import User


class SkillViewSetTests(TestCase):
    """Tests for SkillViewSet."""

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
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="testpass123",
            role=User.Role.ADMIN,
            is_staff=True,
            tenant=self.tenant
        )
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            role=User.Role.LEARNER,
            tenant=self.tenant
        )

        # Create test skills
        self.parent_skill = Skill.objects.create(
            tenant=self.tenant,
            name="Programming",
            slug="programming",
            category=Skill.Category.TECHNICAL,
            description="General programming skills"
        )
        self.child_skill = Skill.objects.create(
            tenant=self.tenant,
            name="Python",
            slug="python",
            category=Skill.Category.TECHNICAL,
            parent=self.parent_skill,
            description="Python programming"
        )
        self.soft_skill = Skill.objects.create(
            tenant=self.tenant,
            name="Communication",
            slug="communication",
            category=Skill.Category.SOFT,
            description="Communication skills"
        )
        self.inactive_skill = Skill.objects.create(
            tenant=self.tenant,
            name="Deprecated Skill",
            slug="deprecated",
            category=Skill.Category.OTHER,
            is_active=False
        )

    def _get_url(self, action, slug=None):
        """Get URL for skill actions."""
        if action == 'list':
            return reverse('skills:skill-list')
        elif action == 'detail':
            return reverse('skills:skill-detail', kwargs={'slug': slug})
        elif action == 'hierarchy':
            return reverse('skills:skill-hierarchy')
        elif action == 'categories':
            return reverse('skills:skill-categories')
        elif action == 'modules':
            return reverse('skills:skill-modules', kwargs={'slug': slug})
        elif action == 'progress_stats':
            return reverse('skills:skill-progress-stats', kwargs={'slug': slug})
        return None

    # --- List Tests ---
    def test_list_skills_as_authenticated_user(self):
        """Test that authenticated users can list skills."""
        self.client.force_authenticate(user=self.learner)
        response = self.client.get(
            self._get_url('list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        # Should see all skills (including inactive) since no default filter is applied
        self.assertEqual(len(results), 4)

    def test_list_skills_unauthenticated(self):
        """Test that unauthenticated users cannot list skills."""
        response = self.client.get(
            self._get_url('list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_skills_filter_by_category(self):
        """Test filtering skills by category."""
        self.client.force_authenticate(user=self.learner)
        response = self.client.get(
            self._get_url('list') + f'?category={Skill.Category.TECHNICAL}',
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 2)  # programming, python

    def test_list_skills_filter_by_parent_root(self):
        """Test filtering for root-level skills."""
        self.client.force_authenticate(user=self.learner)
        response = self.client.get(
            self._get_url('list') + '?parent=root',
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        # Root skills: programming, communication, deprecated (inactive)
        self.assertEqual(len(results), 3)

    def test_list_skills_filter_by_is_active(self):
        """Test filtering by active status."""
        self.client.force_authenticate(user=self.learner)
        response = self.client.get(
            self._get_url('list') + '?is_active=false',
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['name'], 'Deprecated Skill')

    def test_list_skills_search(self):
        """Test searching skills by name or description."""
        self.client.force_authenticate(user=self.learner)
        response = self.client.get(
            self._get_url('list') + '?search=python',
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['name'], 'Python')

    # --- Retrieve Tests ---
    def test_retrieve_skill_as_learner(self):
        """Test that learners can retrieve skill details."""
        self.client.force_authenticate(user=self.learner)
        response = self.client.get(
            self._get_url('detail', slug=self.child_skill.slug),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Python')
        self.assertEqual(response.data['category'], Skill.Category.TECHNICAL)

    # --- Create Tests ---
    def test_create_skill_as_instructor(self):
        """Test that instructors can create skills."""
        self.client.force_authenticate(user=self.instructor)
        data = {
            'name': 'JavaScript',
            'category': Skill.Category.TECHNICAL,
            'description': 'JavaScript programming'
        }
        response = self.client.post(
            self._get_url('list'),
            data,
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], 'JavaScript')
        self.assertTrue(Skill.objects.filter(slug='javascript').exists())

    def test_create_skill_as_learner_forbidden(self):
        """Test that learners cannot create skills."""
        self.client.force_authenticate(user=self.learner)
        data = {
            'name': 'New Skill',
            'category': Skill.Category.OTHER
        }
        response = self.client.post(
            self._get_url('list'),
            data,
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_skill_with_parent(self):
        """Test creating a child skill."""
        self.client.force_authenticate(user=self.instructor)
        data = {
            'name': 'Django',
            'category': Skill.Category.TECHNICAL,
            'parent': str(self.child_skill.id),  # Child of Python
            'description': 'Django web framework'
        }
        response = self.client.post(
            self._get_url('list'),
            data,
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        skill = Skill.objects.get(slug='django')
        self.assertEqual(skill.parent_id, self.child_skill.id)

    # --- Update Tests ---
    def test_update_skill_as_instructor(self):
        """Test that instructors can update skills."""
        self.client.force_authenticate(user=self.instructor)
        data = {
            'name': 'Python Programming',
            'category': Skill.Category.TECHNICAL,
            'description': 'Updated description'
        }
        response = self.client.put(
            self._get_url('detail', slug=self.child_skill.slug),
            data,
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.child_skill.refresh_from_db()
        self.assertEqual(self.child_skill.name, 'Python Programming')

    def test_partial_update_skill(self):
        """Test partial update of a skill."""
        self.client.force_authenticate(user=self.instructor)
        data = {'description': 'New description'}
        response = self.client.patch(
            self._get_url('detail', slug=self.child_skill.slug),
            data,
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.child_skill.refresh_from_db()
        self.assertEqual(self.child_skill.description, 'New description')

    # --- Delete Tests ---
    def test_delete_skill_as_admin(self):
        """Test that admins can delete skills."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(
            self._get_url('detail', slug=self.soft_skill.slug),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Skill.objects.filter(slug='communication').exists())

    # --- Custom Action Tests ---
    def test_hierarchy_action(self):
        """Test getting skill hierarchy."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.get(
            self._get_url('hierarchy'),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should return root skills with children nested
        root_names = [s['name'] for s in response.data]
        self.assertIn('Programming', root_names)
        self.assertIn('Communication', root_names)

    def test_categories_action(self):
        """Test getting skill categories with counts."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.get(
            self._get_url('categories'),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        categories = {c['value']: c['count'] for c in response.data}
        self.assertEqual(categories.get(Skill.Category.TECHNICAL), 2)
        self.assertEqual(categories.get(Skill.Category.SOFT), 1)


class ModuleSkillViewSetTests(TestCase):
    """Tests for ModuleSkillViewSet."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()

        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
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
        self.module = Module.objects.create(
            course=self.course,
            title="Test Module",
            order=1
        )
        self.skill = Skill.objects.create(
            tenant=self.tenant,
            name="Python",
            slug="python",
            category=Skill.Category.TECHNICAL
        )
        self.module_skill = ModuleSkill.objects.create(
            module=self.module,
            skill=self.skill,
            contribution_level=ModuleSkill.ContributionLevel.DEVELOPS,
            proficiency_gained=15
        )

    def _get_url(self, action, pk=None):
        """Get URL for module-skill actions."""
        if action == 'list':
            return reverse('skills:module-skill-list')
        elif action == 'detail':
            return reverse('skills:module-skill-detail', kwargs={'pk': pk})
        elif action == 'bulk_create':
            return reverse('skills:module-skill-bulk-create')
        return None

    def test_list_module_skills_as_instructor(self):
        """Test listing module-skill mappings."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.get(
            self._get_url('list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 1)

    def test_list_module_skills_as_learner_forbidden(self):
        """Test that learners cannot list module-skill mappings."""
        self.client.force_authenticate(user=self.learner)
        response = self.client.get(
            self._get_url('list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_filter_by_module(self):
        """Test filtering module-skills by module."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.get(
            self._get_url('list') + f'?module={self.module.id}',
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 1)

    def test_create_module_skill(self):
        """Test creating a module-skill mapping."""
        self.client.force_authenticate(user=self.instructor)
        new_skill = Skill.objects.create(
            tenant=self.tenant,
            name="Django",
            slug="django",
            category=Skill.Category.TECHNICAL
        )
        data = {
            'module': str(self.module.id),
            'skill': str(new_skill.id),
            'contribution_level': ModuleSkill.ContributionLevel.INTRODUCES,
            'proficiency_gained': 10
        }
        response = self.client.post(
            self._get_url('list'),
            data,
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_bulk_create_module_skills(self):
        """Test bulk creating module-skill mappings."""
        self.client.force_authenticate(user=self.instructor)
        skill2 = Skill.objects.create(
            tenant=self.tenant,
            name="JavaScript",
            slug="javascript",
            category=Skill.Category.TECHNICAL
        )
        skill3 = Skill.objects.create(
            tenant=self.tenant,
            name="HTML",
            slug="html",
            category=Skill.Category.TECHNICAL
        )
        data = {
            'module_id': str(self.module.id),
            'skill_ids': [str(skill2.id), str(skill3.id)],
            'contribution_level': ModuleSkill.ContributionLevel.DEVELOPS,
            'proficiency_gained': 12
        }
        response = self.client.post(
            self._get_url('bulk_create'),
            data,
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data), 2)


class LearnerSkillProgressViewSetTests(TestCase):
    """Tests for LearnerSkillProgressViewSet."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()

        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
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

        self.skill = Skill.objects.create(
            tenant=self.tenant,
            name="Python",
            slug="python",
            category=Skill.Category.TECHNICAL
        )
        self.progress = LearnerSkillProgress.objects.create(
            user=self.learner,
            skill=self.skill,
            proficiency_score=45,
            proficiency_level=Skill.ProficiencyLevel.BEGINNER
        )
        self.other_progress = LearnerSkillProgress.objects.create(
            user=self.other_learner,
            skill=self.skill,
            proficiency_score=70,
            proficiency_level=Skill.ProficiencyLevel.ADVANCED
        )

    def _get_url(self, action, pk=None):
        """Get URL for skill progress actions."""
        if action == 'list':
            return reverse('skills:skill-progress-list')
        elif action == 'detail':
            return reverse('skills:skill-progress-detail', kwargs={'pk': pk})
        elif action == 'my_progress':
            return reverse('skills:skill-progress-my-progress')
        elif action == 'skill_gaps':
            return reverse('skills:skill-progress-skill-gaps')
        return None

    def test_list_progress_as_learner_own_only(self):
        """Test that learners only see their own progress."""
        self.client.force_authenticate(user=self.learner)
        response = self.client.get(
            self._get_url('list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['proficiency_score'], 45)

    def test_list_progress_as_instructor_sees_all(self):
        """Test that instructors see all progress in tenant."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.get(
            self._get_url('list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 2)

    def test_my_progress_action(self):
        """Test getting current user's skill progress summary."""
        self.client.force_authenticate(user=self.learner)
        response = self.client.get(
            self._get_url('my_progress'),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_skills'], 1)
        self.assertEqual(response.data['average_proficiency'], 45.0)

    def test_skill_gaps_action(self):
        """Test getting skill gaps for user."""
        # Create a course and module with skill mapping to make the skill "learnable"
        course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED
        )
        module = Module.objects.create(
            course=course,
            title="Test Module",
            order=1
        )
        ModuleSkill.objects.create(
            module=module,
            skill=self.skill,
            contribution_level=ModuleSkill.ContributionLevel.DEVELOPS
        )

        self.client.force_authenticate(user=self.learner)
        response = self.client.get(
            self._get_url('skill_gaps'),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Learner has 45 proficiency, target is 50, so there should be a gap
        self.assertTrue(len(response.data) >= 1)


class AssessmentSkillMappingViewSetTests(TestCase):
    """Tests for AssessmentSkillMappingViewSet."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()

        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
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
            assessment_type=Assessment.AssessmentType.QUIZ
        )
        self.question = Question.objects.create(
            assessment=self.assessment,
            question_type=Question.QuestionType.MULTIPLE_CHOICE,
            question_text="What is Python?",
            points=10,
            order=1
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

    def _get_url(self, action, pk=None):
        """Get URL for assessment-skill mapping actions."""
        if action == 'list':
            return reverse('skills:assessment-skill-mapping-list')
        elif action == 'detail':
            return reverse('skills:assessment-skill-mapping-detail', kwargs={'pk': pk})
        elif action == 'bulk_create':
            return reverse('skills:assessment-skill-mapping-bulk-create')
        elif action == 'coverage':
            return reverse('skills:assessment-skill-mapping-coverage')
        return None

    def test_list_mappings_as_instructor(self):
        """Test listing assessment-skill mappings."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.get(
            self._get_url('list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 1)

    def test_filter_by_assessment(self):
        """Test filtering mappings by assessment."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.get(
            self._get_url('list') + f'?assessment={self.assessment.id}',
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 1)

    def test_coverage_action(self):
        """Test getting skill coverage for an assessment."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.get(
            self._get_url('coverage') + f'?assessment_id={self.assessment.id}',
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['assessment_id'], str(self.assessment.id))
        self.assertEqual(response.data['skills_covered'], 1)
        self.assertEqual(len(response.data['skills']), 1)

    def test_coverage_action_missing_assessment_id(self):
        """Test coverage action requires assessment_id."""
        self.client.force_authenticate(user=self.instructor)
        response = self.client.get(
            self._get_url('coverage'),
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_create_mappings(self):
        """Test bulk creating assessment-skill mappings."""
        self.client.force_authenticate(user=self.instructor)
        question2 = Question.objects.create(
            assessment=self.assessment,
            question_type=Question.QuestionType.MULTIPLE_CHOICE,
            question_text="Question 2",
            points=10,
            order=2
        )
        skill2 = Skill.objects.create(
            tenant=self.tenant,
            name="Django",
            slug="django",
            category=Skill.Category.TECHNICAL
        )
        data = {
            'mappings': [
                {
                    'question_id': str(question2.id),
                    'skill_id': str(self.skill.id),
                    'weight': 1,
                    'proficiency_required': Skill.ProficiencyLevel.BEGINNER
                },
                {
                    'question_id': str(question2.id),
                    'skill_id': str(skill2.id),
                    'weight': 2,
                    'proficiency_required': Skill.ProficiencyLevel.INTERMEDIATE
                }
            ]
        }
        response = self.client.post(
            self._get_url('bulk_create'),
            data,
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data), 2)
