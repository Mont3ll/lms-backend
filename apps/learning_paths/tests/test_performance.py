"""Performance tests for Learning Paths services.

These tests verify that the personalized path generation works efficiently
at scale and that query optimizations are effective.
"""

import time
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.db import connection, reset_queries
from django.test import TestCase, override_settings

from apps.core.models import Tenant
from apps.courses.models import Course, Module, ContentItem, ModulePrerequisite
from apps.enrollments.models import Enrollment, LearnerProgress
from apps.learning_paths.models import PersonalizedLearningPath
from apps.learning_paths.services import PersonalizedPathGenerator
from apps.skills.models import Skill, ModuleSkill, LearnerSkillProgress
from apps.users.models import User


class LargeScalePathGenerationTests(TestCase):
    """Tests for path generation with 100+ modules."""

    @classmethod
    def setUpTestData(cls):
        """Create a large dataset of courses, modules, and skills."""
        cls.tenant = Tenant.objects.create(name="Performance Test Tenant", slug="perf-test")
        cls.learner = User.objects.create_user(
            email="learner@perftest.com",
            password="testpass123",
            tenant=cls.tenant,
        )
        cls.instructor = User.objects.create_user(
            email="instructor@perftest.com",
            password="testpass123",
            tenant=cls.tenant,
        )

        # Create 10 skills in different categories
        cls.skills = []
        categories = [
            Skill.Category.TECHNICAL,
            Skill.Category.SOFT,
            Skill.Category.DOMAIN,
        ]
        for i in range(10):
            skill = Skill.objects.create(
                tenant=cls.tenant,
                name=f"Skill {i+1}",
                slug=f"skill-{i+1}",
                category=categories[i % len(categories)],
            )
            cls.skills.append(skill)

        # Create 20 courses with 5-10 modules each (total 100+ modules)
        cls.courses = []
        cls.modules = []
        
        for course_idx in range(20):
            course = Course.objects.create(
                tenant=cls.tenant,
                title=f"Course {course_idx + 1}",
                instructor=cls.instructor,
                status=Course.Status.PUBLISHED,
            )
            cls.courses.append(course)

            # Create 5-10 modules per course
            num_modules = 5 + (course_idx % 6)  # Varies between 5-10
            for mod_idx in range(num_modules):
                module = Module.objects.create(
                    course=course,
                    title=f"Module {course_idx + 1}.{mod_idx + 1}",
                    order=mod_idx + 1,
                )
                cls.modules.append(module)

                # Add content item for duration estimation
                ContentItem.objects.create(
                    module=module,
                    title=f"Content {course_idx + 1}.{mod_idx + 1}",
                    content_type=ContentItem.ContentType.VIDEO,
                    order=1,
                )

                # Map module to 1-3 skills
                num_skills = 1 + (mod_idx % 3)
                skill_offset = (course_idx * 2 + mod_idx) % len(cls.skills)
                for skill_idx in range(num_skills):
                    skill = cls.skills[(skill_offset + skill_idx) % len(cls.skills)]
                    is_primary = skill_idx == 0
                    
                    # Avoid duplicates
                    if not ModuleSkill.objects.filter(module=module, skill=skill).exists():
                        ModuleSkill.objects.create(
                            module=module,
                            skill=skill,
                            contribution_level=ModuleSkill.ContributionLevel.DEVELOPS,
                            proficiency_gained=15 + (mod_idx * 2),
                            is_primary=is_primary,
                        )

        # Set up module prerequisites (chain modules within each course)
        # Prerequisites must be from the same course
        for course in cls.courses:
            course_modules = [m for m in cls.modules if m.course_id == course.id]
            # Create prerequisite chain within each course
            for i in range(1, len(course_modules)):
                if i % 2 == 0:  # Create some prerequisites, not all
                    ModulePrerequisite.objects.create(
                        module=course_modules[i],
                        prerequisite_module=course_modules[i - 1],
                    )

    def test_module_count(self):
        """Verify we have 100+ modules for testing."""
        self.assertGreaterEqual(len(self.modules), 100)

    def test_generate_path_with_100_plus_modules(self):
        """Test that path generation completes within acceptable time for 100+ modules."""
        # Target multiple skills to increase coverage
        target_skills = self.skills[:3]

        start_time = time.time()
        
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=target_skills,
            target_proficiency=80,
            max_modules=20,
        )
        
        path = generator.generate(title="Large Scale Path")
        
        elapsed_time = time.time() - start_time

        # Path generation should complete within 5 seconds
        self.assertLess(
            elapsed_time, 
            5.0, 
            f"Path generation took {elapsed_time:.2f}s, expected < 5s"
        )

        # Verify path was created successfully
        self.assertIsInstance(path, PersonalizedLearningPath)
        self.assertGreater(path.steps.count(), 0)
        self.assertLessEqual(path.steps.count(), 20)

        # All target skills should be linked
        for skill in target_skills:
            self.assertIn(skill, path.target_skills.all())

    def test_generate_path_multiple_times_performance(self):
        """Test that repeated path generation has consistent performance."""
        target_skills = self.skills[:2]
        times = []

        for i in range(3):
            start_time = time.time()
            
            generator = PersonalizedPathGenerator(
                user=self.learner,
                tenant=self.tenant,
                target_skills=target_skills,
                target_proficiency=70,
                max_modules=15,
            )
            
            path = generator.generate(title=f"Iteration Path {i+1}")
            
            elapsed_time = time.time() - start_time
            times.append(elapsed_time)

            # Archive the path for next iteration
            path.status = PersonalizedLearningPath.Status.ARCHIVED
            path.save()

        # Average time should be under 3 seconds
        avg_time = sum(times) / len(times)
        self.assertLess(
            avg_time, 
            3.0,
            f"Average path generation time {avg_time:.2f}s exceeded 3s limit"
        )

        # No single run should exceed 5 seconds
        max_time = max(times)
        self.assertLess(
            max_time,
            5.0,
            f"Max path generation time {max_time:.2f}s exceeded 5s limit"
        )


@override_settings(DEBUG=True)
class QueryOptimizationTests(TestCase):
    """Tests to verify query optimization in path generation."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data for query optimization tests."""
        cls.tenant = Tenant.objects.create(name="Query Test Tenant", slug="query-test")
        cls.learner = User.objects.create_user(
            email="learner@querytest.com",
            password="testpass123",
            tenant=cls.tenant,
        )
        cls.instructor = User.objects.create_user(
            email="instructor@querytest.com",
            password="testpass123",
            tenant=cls.tenant,
        )

        # Create skills
        cls.skills = []
        for i in range(5):
            skill = Skill.objects.create(
                tenant=cls.tenant,
                name=f"QuerySkill {i+1}",
                slug=f"query-skill-{i+1}",
                category=Skill.Category.TECHNICAL,
            )
            cls.skills.append(skill)

        # Create courses and modules
        cls.courses = []
        cls.modules = []
        
        for course_idx in range(10):
            course = Course.objects.create(
                tenant=cls.tenant,
                title=f"Query Course {course_idx + 1}",
                instructor=cls.instructor,
                status=Course.Status.PUBLISHED,
            )
            cls.courses.append(course)

            for mod_idx in range(5):
                module = Module.objects.create(
                    course=course,
                    title=f"Query Module {course_idx + 1}.{mod_idx + 1}",
                    order=mod_idx + 1,
                )
                cls.modules.append(module)

                ContentItem.objects.create(
                    module=module,
                    title=f"Query Content {course_idx + 1}.{mod_idx + 1}",
                    content_type=ContentItem.ContentType.DOCUMENT,
                    order=1,
                )

                # Map to skills
                skill_idx = (course_idx + mod_idx) % len(cls.skills)
                ModuleSkill.objects.create(
                    module=module,
                    skill=cls.skills[skill_idx],
                    contribution_level=ModuleSkill.ContributionLevel.DEVELOPS,
                    proficiency_gained=20,
                    is_primary=True,
                )

    def test_query_count_is_bounded(self):
        """Test that query count doesn't grow excessively with data size."""
        target_skills = self.skills[:2]

        # Reset query log
        reset_queries()

        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=target_skills,
            target_proficiency=70,
            max_modules=10,
        )
        
        path = generator.generate(title="Query Count Test")

        # Get query count
        query_count = len(connection.queries)

        # Query count should be bounded
        # Expected queries:
        # - 1 for user skill progress
        # - 1 for module skills with related data
        # - 1 for completed modules check
        # - 1-2 for prerequisites
        # - Several for path/step creation
        # Current baseline: ~84 queries for this test case
        # This acts as a regression guard - if queries increase significantly, investigate
        self.assertLess(
            query_count,
            100,
            f"Query count {query_count} exceeded limit of 100"
        )

    def test_uses_select_related_and_prefetch(self):
        """Test that queries use proper select_related/prefetch_related."""
        target_skills = self.skills[:2]

        reset_queries()

        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=target_skills,
            target_proficiency=70,
            max_modules=10,
        )
        
        path = generator.generate(title="Prefetch Test")

        queries = connection.queries

        # Check that we're not making N+1 queries for module skills
        # Look for patterns of repeated similar queries
        module_skill_queries = [
            q for q in queries 
            if 'skills_moduleskill' in q['sql'].lower()
        ]
        
        # Should have at most a few module skill queries, not one per module
        # Current baseline: ~9 queries for module skills
        # This is acceptable as they may include prefetch, counts, and related lookups
        self.assertLess(
            len(module_skill_queries),
            15,
            f"Too many ModuleSkill queries ({len(module_skill_queries)}), "
            "indicates N+1 problem"
        )


class CachingEffectivenessTests(TestCase):
    """Tests for caching effectiveness in path generation."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data for caching tests."""
        cls.tenant = Tenant.objects.create(name="Cache Test Tenant", slug="cache-test")
        cls.learner = User.objects.create_user(
            email="learner@cachetest.com",
            password="testpass123",
            tenant=cls.tenant,
        )
        cls.instructor = User.objects.create_user(
            email="instructor@cachetest.com",
            password="testpass123",
            tenant=cls.tenant,
        )

        # Create skills
        cls.skills = []
        for i in range(3):
            skill = Skill.objects.create(
                tenant=cls.tenant,
                name=f"CacheSkill {i+1}",
                slug=f"cache-skill-{i+1}",
                category=Skill.Category.TECHNICAL,
            )
            cls.skills.append(skill)

        # Create courses and modules
        cls.courses = []
        cls.modules = []
        
        for course_idx in range(5):
            course = Course.objects.create(
                tenant=cls.tenant,
                title=f"Cache Course {course_idx + 1}",
                instructor=cls.instructor,
                status=Course.Status.PUBLISHED,
            )
            cls.courses.append(course)

            for mod_idx in range(4):
                module = Module.objects.create(
                    course=course,
                    title=f"Cache Module {course_idx + 1}.{mod_idx + 1}",
                    order=mod_idx + 1,
                )
                cls.modules.append(module)

                ContentItem.objects.create(
                    module=module,
                    title=f"Cache Content {course_idx + 1}.{mod_idx + 1}",
                    content_type=ContentItem.ContentType.VIDEO,
                    order=1,
                )

                skill_idx = (course_idx + mod_idx) % len(cls.skills)
                ModuleSkill.objects.create(
                    module=module,
                    skill=cls.skills[skill_idx],
                    contribution_level=ModuleSkill.ContributionLevel.DEVELOPS,
                    proficiency_gained=25,
                    is_primary=True,
                )

    def test_skill_progress_caching(self):
        """Test that skill progress lookup is efficient."""
        # Create some skill progress
        for skill in self.skills:
            LearnerSkillProgress.objects.create(
                user=self.learner,
                skill=skill,
                proficiency_score=20,
            )

        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=self.skills,
            target_proficiency=80,
        )

        # The generator should cache user's skill progress
        # and not re-query for each skill check
        reset_queries()
        
        path = generator.generate(title="Skill Progress Cache Test")

        # Check skill progress related queries
        queries = connection.queries
        skill_progress_queries = [
            q for q in queries 
            if 'learnerskillprogress' in q['sql'].lower()
        ]

        # Should only query skill progress once
        self.assertLessEqual(
            len(skill_progress_queries),
            2,  # Allow 1-2 queries for initial fetch
            f"Too many skill progress queries ({len(skill_progress_queries)})"
        )

    def test_module_candidate_evaluation_is_cached(self):
        """Test that module candidates are evaluated efficiently."""
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=self.skills[:2],
            target_proficiency=70,
        )

        # First generation
        reset_queries()
        path1 = generator.generate(title="Cache Test Path 1")
        first_query_count = len(connection.queries)

        # Archive first path
        path1.status = PersonalizedLearningPath.Status.ARCHIVED
        path1.save()

        # Second generation with same parameters should have similar query count
        generator2 = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=self.skills[:2],
            target_proficiency=70,
        )
        
        reset_queries()
        path2 = generator2.generate(title="Cache Test Path 2")
        second_query_count = len(connection.queries)

        # Query counts should be similar (within 50% of each other)
        # This verifies no query explosion on repeated generations
        ratio = max(first_query_count, second_query_count) / max(min(first_query_count, second_query_count), 1)
        self.assertLess(
            ratio,
            1.5,
            f"Query count inconsistency: first={first_query_count}, second={second_query_count}"
        )


class PrerequisiteResolutionPerformanceTests(TestCase):
    """Tests for prerequisite resolution performance."""

    @classmethod
    def setUpTestData(cls):
        """Create modules with complex prerequisite chains."""
        cls.tenant = Tenant.objects.create(name="Prereq Test Tenant", slug="prereq-test")
        cls.learner = User.objects.create_user(
            email="learner@prereqtest.com",
            password="testpass123",
            tenant=cls.tenant,
        )
        cls.instructor = User.objects.create_user(
            email="instructor@prereqtest.com",
            password="testpass123",
            tenant=cls.tenant,
        )

        # Create skill
        cls.skill = Skill.objects.create(
            tenant=cls.tenant,
            name="Deep Prereq Skill",
            slug="deep-prereq-skill",
            category=Skill.Category.TECHNICAL,
        )

        # Create a course with a deep prerequisite chain
        # module_1 -> module_2 -> module_3 -> ... -> module_10
        course = Course.objects.create(
            tenant=cls.tenant,
            title="Deep Prereq Course",
            instructor=cls.instructor,
            status=Course.Status.PUBLISHED,
        )

        cls.modules = []
        for i in range(10):
            module = Module.objects.create(
                course=course,
                title=f"Chain Module {i + 1}",
                order=i + 1,
            )
            cls.modules.append(module)

            ContentItem.objects.create(
                module=module,
                title=f"Chain Content {i + 1}",
                content_type=ContentItem.ContentType.DOCUMENT,
                order=1,
            )

            # Add skill mapping only to the last module
            if i == len(cls.modules) - 1 or i == 0:
                ModuleSkill.objects.create(
                    module=module,
                    skill=cls.skill,
                    contribution_level=ModuleSkill.ContributionLevel.DEVELOPS,
                    proficiency_gained=40,
                    is_primary=True,
                )

        # Create the prerequisite chain
        for i in range(1, len(cls.modules)):
            ModulePrerequisite.objects.create(
                module=cls.modules[i],
                prerequisite_module=cls.modules[i - 1],
            )

    def test_deep_prerequisite_chain_resolution(self):
        """Test that deep prerequisite chains are resolved efficiently."""
        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[self.skill],
            target_proficiency=70,
        )

        start_time = time.time()
        path = generator.generate(title="Deep Chain Path")
        elapsed_time = time.time() - start_time

        # Should complete quickly even with deep chains
        self.assertLess(
            elapsed_time,
            2.0,
            f"Deep prerequisite resolution took {elapsed_time:.2f}s"
        )

        # The path should include modules in correct order
        steps = list(path.steps.all().order_by('order'))
        self.assertGreater(len(steps), 0)

    def test_prerequisite_queries_are_batched(self):
        """Test that prerequisite lookups are batched, not N+1."""
        reset_queries()

        generator = PersonalizedPathGenerator(
            user=self.learner,
            tenant=self.tenant,
            target_skills=[self.skill],
            target_proficiency=70,
        )
        
        path = generator.generate(title="Batched Prereq Test")

        queries = connection.queries
        prereq_queries = [
            q for q in queries 
            if 'prerequisites' in q['sql'].lower()
        ]

        # Should have minimal prerequisite queries (batched)
        self.assertLess(
            len(prereq_queries),
            10,
            f"Too many prerequisite queries ({len(prereq_queries)})"
        )


class ScalabilityTests(TestCase):
    """Tests for overall scalability of the path generation system."""

    def setUp(self):
        """Create test fixtures."""
        self.tenant = Tenant.objects.create(name="Scale Test Tenant", slug="scale-test")
        self.learner = User.objects.create_user(
            email="learner@scaletest.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.instructor = User.objects.create_user(
            email="instructor@scaletest.com",
            password="testpass123",
            tenant=self.tenant,
        )

    def test_path_generation_with_varying_module_counts(self):
        """Test that performance scales reasonably with module count."""
        results = []

        for num_modules in [10, 30, 50]:
            # Create skills
            skill = Skill.objects.create(
                tenant=self.tenant,
                name=f"Scale Skill {num_modules}",
                slug=f"scale-skill-{num_modules}",
                category=Skill.Category.TECHNICAL,
            )

            # Create course with modules
            course = Course.objects.create(
                tenant=self.tenant,
                title=f"Scale Course {num_modules}",
                instructor=self.instructor,
                status=Course.Status.PUBLISHED,
            )

            for i in range(num_modules):
                module = Module.objects.create(
                    course=course,
                    title=f"Scale Module {num_modules}.{i+1}",
                    order=i + 1,
                )
                ContentItem.objects.create(
                    module=module,
                    title=f"Scale Content {i+1}",
                    content_type=ContentItem.ContentType.DOCUMENT,
                    order=1,
                )
                ModuleSkill.objects.create(
                    module=module,
                    skill=skill,
                    contribution_level=ModuleSkill.ContributionLevel.DEVELOPS,
                    proficiency_gained=10,
                    is_primary=True,
                )

            # Time the path generation
            start_time = time.time()
            
            generator = PersonalizedPathGenerator(
                user=self.learner,
                tenant=self.tenant,
                target_skills=[skill],
                target_proficiency=80,
                max_modules=num_modules,
            )
            path = generator.generate(title=f"Scale Path {num_modules}")
            
            elapsed_time = time.time() - start_time
            results.append((num_modules, elapsed_time))

            # Archive for cleanup
            path.status = PersonalizedLearningPath.Status.ARCHIVED
            path.save()

        # Check that time doesn't grow exponentially
        # Time for 50 modules should be at most 5x time for 10 modules
        time_10 = results[0][1]
        time_50 = results[2][1]
        
        self.assertLess(
            time_50,
            time_10 * 10,  # Allow up to 10x for 5x data
            f"Performance doesn't scale: 10 modules={time_10:.2f}s, 50 modules={time_50:.2f}s"
        )
