"""Tests for courses app models."""

from decimal import Decimal
from django.test import TestCase
from django.db import IntegrityError

from apps.courses.models import Course, Module, ContentItem, ContentVersion
from apps.core.models import Tenant
from apps.users.models import User


class CourseModelTests(TestCase):
    """Tests for the Course model."""

    def setUp(self):
        """Set up test data."""
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant"
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            first_name="Test",
            last_name="Instructor",
            role=User.Role.INSTRUCTOR,
            tenant=self.tenant
        )

    def test_course_creation(self):
        """Test basic course creation."""
        course = Course.objects.create(
            tenant=self.tenant,
            title="Python Basics",
            description="Learn Python programming",
            instructor=self.instructor
        )
        
        self.assertEqual(course.title, "Python Basics")
        self.assertEqual(course.description, "Learn Python programming")
        self.assertEqual(course.instructor, self.instructor)
        self.assertEqual(course.tenant, self.tenant)
        self.assertEqual(course.status, Course.Status.DRAFT)
        self.assertIsNotNone(course.slug)

    def test_course_slug_auto_generated(self):
        """Test that slug is auto-generated from title."""
        course = Course.objects.create(
            tenant=self.tenant,
            title="Advanced JavaScript Course",
            instructor=self.instructor
        )
        
        self.assertIn("advanced-javascript-course", course.slug)

    def test_course_slug_unique(self):
        """Test that slugs are unique across courses."""
        course1 = Course.objects.create(
            tenant=self.tenant,
            title="Python Basics",
            instructor=self.instructor
        )
        course2 = Course.objects.create(
            tenant=self.tenant,
            title="Python Basics",  # Same title
            instructor=self.instructor
        )
        
        # Slugs should be different even with same title
        self.assertNotEqual(course1.slug, course2.slug)

    def test_course_status_choices(self):
        """Test course status choices."""
        course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            instructor=self.instructor
        )
        
        # Default should be DRAFT
        self.assertEqual(course.status, Course.Status.DRAFT)
        
        # Can change to PUBLISHED
        course.status = Course.Status.PUBLISHED
        course.save()
        course.refresh_from_db()
        self.assertEqual(course.status, Course.Status.PUBLISHED)
        
        # Can change to ARCHIVED
        course.status = Course.Status.ARCHIVED
        course.save()
        course.refresh_from_db()
        self.assertEqual(course.status, Course.Status.ARCHIVED)

    def test_course_difficulty_levels(self):
        """Test course difficulty level choices."""
        course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            instructor=self.instructor
        )
        
        # Default is BEGINNER
        self.assertEqual(course.difficulty_level, Course.DifficultyLevel.BEGINNER)
        
        # Can set to INTERMEDIATE
        course.difficulty_level = Course.DifficultyLevel.INTERMEDIATE
        course.save()
        course.refresh_from_db()
        self.assertEqual(course.difficulty_level, Course.DifficultyLevel.INTERMEDIATE)
        
        # Can set to ADVANCED
        course.difficulty_level = Course.DifficultyLevel.ADVANCED
        course.save()
        course.refresh_from_db()
        self.assertEqual(course.difficulty_level, Course.DifficultyLevel.ADVANCED)

    def test_course_pricing_fields(self):
        """Test course pricing fields."""
        course = Course.objects.create(
            tenant=self.tenant,
            title="Premium Course",
            instructor=self.instructor,
            is_free=False,
            price=Decimal("99.99")
        )
        
        self.assertFalse(course.is_free)
        self.assertEqual(course.price, Decimal("99.99"))

    def test_course_learning_objectives(self):
        """Test course learning objectives JSON field."""
        objectives = [
            "Understand Python basics",
            "Write Python functions",
            "Use Python libraries"
        ]
        course = Course.objects.create(
            tenant=self.tenant,
            title="Python Course",
            instructor=self.instructor,
            learning_objectives=objectives
        )
        
        self.assertEqual(course.learning_objectives, objectives)
        self.assertEqual(len(course.learning_objectives), 3)

    def test_course_tags(self):
        """Test course tags JSON field."""
        tags = ["python", "programming", "beginner"]
        course = Course.objects.create(
            tenant=self.tenant,
            title="Python Course",
            instructor=self.instructor,
            tags=tags
        )
        
        self.assertEqual(course.tags, tags)

    def test_course_str_representation(self):
        """Test course string representation."""
        course = Course.objects.create(
            tenant=self.tenant,
            title="Python Basics",
            instructor=self.instructor
        )
        
        self.assertEqual(str(course), "Python Basics (Test Tenant)")

    def test_course_without_instructor(self):
        """Test course can be created without instructor."""
        course = Course.objects.create(
            tenant=self.tenant,
            title="Self-Paced Course"
        )
        
        self.assertIsNone(course.instructor)


class ModuleModelTests(TestCase):
    """Tests for the Module model."""

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
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            instructor=self.instructor
        )

    def test_module_creation(self):
        """Test basic module creation."""
        module = Module.objects.create(
            course=self.course,
            title="Introduction",
            description="Getting started with the course",
            order=1
        )
        
        self.assertEqual(module.title, "Introduction")
        self.assertEqual(module.description, "Getting started with the course")
        self.assertEqual(module.order, 1)
        self.assertEqual(module.course, self.course)

    def test_module_ordering(self):
        """Test module ordering within a course."""
        module1 = Module.objects.create(course=self.course, title="Module 1", order=1)
        module2 = Module.objects.create(course=self.course, title="Module 2", order=2)
        module3 = Module.objects.create(course=self.course, title="Module 3", order=3)
        
        modules = list(Module.objects.filter(course=self.course).order_by('order'))
        self.assertEqual(modules, [module1, module2, module3])

    def test_module_str_representation(self):
        """Test module string representation."""
        module = Module.objects.create(
            course=self.course,
            title="Introduction",
            order=1
        )
        
        self.assertEqual(str(module), "Introduction (Course: Test Course)")

    def test_module_cascade_delete(self):
        """Test that modules are deleted when course is deleted."""
        module = Module.objects.create(
            course=self.course,
            title="Test Module",
            order=1
        )
        module_id = module.id
        
        self.course.delete()
        
        self.assertFalse(Module.objects.filter(id=module_id).exists())


class ContentItemModelTests(TestCase):
    """Tests for the ContentItem model."""

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
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            instructor=self.instructor
        )
        self.module = Module.objects.create(
            course=self.course,
            title="Test Module",
            order=1
        )

    def test_text_content_item_creation(self):
        """Test creating a TEXT content item."""
        content_item = ContentItem.objects.create(
            module=self.module,
            title="Welcome Message",
            content_type=ContentItem.ContentType.TEXT,
            text_content="# Welcome to the course\n\nLet's get started!",
            order=1
        )
        
        self.assertEqual(content_item.title, "Welcome Message")
        self.assertEqual(content_item.content_type, ContentItem.ContentType.TEXT)
        self.assertIn("Welcome to the course", content_item.text_content)
        self.assertIsNone(content_item.external_url)

    def test_url_content_item_creation(self):
        """Test creating a URL content item."""
        content_item = ContentItem.objects.create(
            module=self.module,
            title="External Resource",
            content_type=ContentItem.ContentType.URL,
            external_url="https://example.com/resource",
            order=1
        )
        
        self.assertEqual(content_item.content_type, ContentItem.ContentType.URL)
        self.assertEqual(content_item.external_url, "https://example.com/resource")

    def test_video_content_item_creation(self):
        """Test creating a VIDEO content item with external URL."""
        content_item = ContentItem.objects.create(
            module=self.module,
            title="Introduction Video",
            content_type=ContentItem.ContentType.VIDEO,
            external_url="https://youtube.com/watch?v=abc123",
            metadata={"duration": 600, "provider": "youtube"},
            order=1
        )
        
        self.assertEqual(content_item.content_type, ContentItem.ContentType.VIDEO)
        self.assertEqual(content_item.metadata["duration"], 600)
        self.assertEqual(content_item.metadata["provider"], "youtube")

    def test_content_item_ordering(self):
        """Test content item ordering within a module."""
        item1 = ContentItem.objects.create(
            module=self.module, title="Item 1",
            content_type=ContentItem.ContentType.TEXT, order=1
        )
        item2 = ContentItem.objects.create(
            module=self.module, title="Item 2",
            content_type=ContentItem.ContentType.TEXT, order=2
        )
        item3 = ContentItem.objects.create(
            module=self.module, title="Item 3",
            content_type=ContentItem.ContentType.TEXT, order=3
        )
        
        items = list(ContentItem.objects.filter(module=self.module).order_by('order'))
        self.assertEqual(items, [item1, item2, item3])

    def test_content_item_is_published_default(self):
        """Test that content items are not published by default."""
        content_item = ContentItem.objects.create(
            module=self.module,
            title="Draft Content",
            content_type=ContentItem.ContentType.TEXT,
            order=1
        )
        
        self.assertFalse(content_item.is_published)

    def test_content_item_is_required_default(self):
        """Test that content items are required by default."""
        content_item = ContentItem.objects.create(
            module=self.module,
            title="Required Content",
            content_type=ContentItem.ContentType.TEXT,
            order=1
        )
        
        self.assertTrue(content_item.is_required)

    def test_content_item_str_representation(self):
        """Test content item string representation."""
        content_item = ContentItem.objects.create(
            module=self.module,
            title="Welcome Video",
            content_type=ContentItem.ContentType.VIDEO,
            order=1
        )
        
        self.assertEqual(str(content_item), "Welcome Video (Video)")

    def test_content_item_cascade_delete(self):
        """Test that content items are deleted when module is deleted."""
        content_item = ContentItem.objects.create(
            module=self.module,
            title="Test Item",
            content_type=ContentItem.ContentType.TEXT,
            order=1
        )
        content_item_id = content_item.id
        
        self.module.delete()
        
        self.assertFalse(ContentItem.objects.filter(id=content_item_id).exists())

    def test_all_content_types(self):
        """Test all content type choices are valid."""
        content_types = [
            ContentItem.ContentType.TEXT,
            ContentItem.ContentType.DOCUMENT,
            ContentItem.ContentType.IMAGE,
            ContentItem.ContentType.VIDEO,
            ContentItem.ContentType.AUDIO,
            ContentItem.ContentType.URL,
            ContentItem.ContentType.H5P,
            ContentItem.ContentType.SCORM,
            ContentItem.ContentType.QUIZ,
        ]
        
        for i, ct in enumerate(content_types):
            item = ContentItem.objects.create(
                module=self.module,
                title=f"Content Type {ct}",
                content_type=ct,
                order=i + 1
            )
            self.assertEqual(item.content_type, ct)


class ContentVersionModelTests(TestCase):
    """Tests for the ContentVersion model."""

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
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            instructor=self.instructor
        )
        self.module = Module.objects.create(
            course=self.course,
            title="Test Module",
            order=1
        )
        self.content_item = ContentItem.objects.create(
            module=self.module,
            title="Versioned Content",
            content_type=ContentItem.ContentType.TEXT,
            text_content="Original content",
            order=1
        )

    def test_version_creation(self):
        """Test creating a content version."""
        version = ContentVersion.objects.create(
            content_item=self.content_item,
            user=self.instructor,
            version_number=1,
            comment="Initial version",
            content_type=self.content_item.content_type,
            text_content=self.content_item.text_content
        )
        
        self.assertEqual(version.version_number, 1)
        self.assertEqual(version.comment, "Initial version")
        self.assertEqual(version.text_content, "Original content")
        self.assertEqual(version.user, self.instructor)

    def test_multiple_versions(self):
        """Test creating multiple versions of content."""
        version1 = ContentVersion.objects.create(
            content_item=self.content_item,
            user=self.instructor,
            version_number=1,
            comment="Version 1",
            content_type=ContentItem.ContentType.TEXT,
            text_content="Content v1"
        )
        
        # Update content item
        self.content_item.text_content = "Content v2"
        self.content_item.save()
        
        version2 = ContentVersion.objects.create(
            content_item=self.content_item,
            user=self.instructor,
            version_number=2,
            comment="Version 2",
            content_type=ContentItem.ContentType.TEXT,
            text_content="Content v2"
        )
        
        versions = self.content_item.versions.all().order_by('-version_number')
        self.assertEqual(versions.count(), 2)
        self.assertEqual(versions[0].version_number, 2)
        self.assertEqual(versions[1].version_number, 1)

    def test_version_unique_constraint(self):
        """Test that version numbers are unique per content item."""
        ContentVersion.objects.create(
            content_item=self.content_item,
            user=self.instructor,
            version_number=1,
            content_type=ContentItem.ContentType.TEXT
        )
        
        with self.assertRaises(IntegrityError):
            ContentVersion.objects.create(
                content_item=self.content_item,
                user=self.instructor,
                version_number=1,  # Same version number
                content_type=ContentItem.ContentType.TEXT
            )

    def test_version_str_representation(self):
        """Test version string representation."""
        version = ContentVersion.objects.create(
            content_item=self.content_item,
            user=self.instructor,
            version_number=1,
            content_type=ContentItem.ContentType.TEXT
        )
        
        self.assertEqual(str(version), "Versioned Content - v1")

    def test_version_cascade_delete(self):
        """Test that versions are deleted when content item is deleted."""
        version = ContentVersion.objects.create(
            content_item=self.content_item,
            user=self.instructor,
            version_number=1,
            content_type=ContentItem.ContentType.TEXT
        )
        version_id = version.id
        
        self.content_item.delete()
        
        self.assertFalse(ContentVersion.objects.filter(id=version_id).exists())

    def test_version_without_user(self):
        """Test creating version without user (e.g., automated versioning)."""
        version = ContentVersion.objects.create(
            content_item=self.content_item,
            version_number=1,
            comment="Automated version",
            content_type=ContentItem.ContentType.TEXT
        )
        
        self.assertIsNone(version.user)

    def test_version_metadata_snapshot(self):
        """Test that version preserves metadata."""
        self.content_item.metadata = {"key": "value", "setting": True}
        self.content_item.save()
        
        version = ContentVersion.objects.create(
            content_item=self.content_item,
            user=self.instructor,
            version_number=1,
            content_type=ContentItem.ContentType.TEXT,
            metadata=self.content_item.metadata
        )
        
        self.assertEqual(version.metadata, {"key": "value", "setting": True})
