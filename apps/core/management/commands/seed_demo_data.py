"""
Comprehensive LMS Database Seeding Script

Seeds the database with realistic demo data covering all models:
- Core: Tenant, TenantDomain, PlatformSettings
- Users: User, LearnerGroup, GroupMembership
- Files: Folder, File
- Courses: Course, Module, ContentItem
- Assessments: Assessment, Question, AssessmentAttempt
- Enrollments: Enrollment, LearnerProgress, Certificate
- Learning Paths: LearningPath, LearningPathStep, Progress
- AI Engine: ModelConfig, PromptTemplate, GenerationJob
- Notifications: Notification, Announcement
- Analytics: Event, Report

Usage:
    python manage.py seed_demo_data
    python manage.py seed_demo_data --clear  # Clear existing data first
"""

import random
import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

User = get_user_model()

# ============================================================================
# CONFIGURATION
# ============================================================================

DEFAULT_PASSWORD = "password123"

TENANT_CONFIGS = [
    {
        "name": "Acme Learning",
        "slug": "acme",
        "domain": "acme.localhost",
        "theme": {"primary_color": "#3B82F6", "logo_text": "Acme Learning"},
    },
    {
        "name": "TechU Academy",
        "slug": "techu",
        "domain": "techu.localhost",
        "theme": {"primary_color": "#10B981", "logo_text": "TechU"},
    },
]

COURSE_DATA = [
    {
        "title": "Python Programming Fundamentals",
        "category": "programming",
        "difficulty": "beginner",
        "description": "Learn Python from scratch. This comprehensive course covers variables, data types, control structures, functions, and object-oriented programming.",
        "objectives": ["Understand Python syntax", "Write functions and classes", "Handle files and exceptions"],
        "modules": [
            {"title": "Getting Started with Python", "items": ["Installing Python", "Your First Program", "Variables and Data Types", "Basic Input/Output"]},
            {"title": "Control Flow", "items": ["If Statements", "Loops", "Break and Continue", "Practice Exercises"]},
            {"title": "Functions and Modules", "items": ["Defining Functions", "Parameters and Return Values", "Built-in Functions", "Creating Modules"]},
        ],
    },
    {
        "title": "Web Development with Django",
        "category": "web_development",
        "difficulty": "intermediate",
        "description": "Build modern web applications with Django. Learn MVC architecture, ORM, templates, forms, and REST APIs.",
        "objectives": ["Build Django applications", "Create REST APIs", "Deploy to production"],
        "modules": [
            {"title": "Django Basics", "items": ["Project Setup", "Models and Migrations", "Admin Interface", "URL Routing"]},
            {"title": "Views and Templates", "items": ["Function-based Views", "Class-based Views", "Template Language", "Static Files"]},
            {"title": "Forms and Authentication", "items": ["Django Forms", "Model Forms", "User Authentication", "Permissions"]},
            {"title": "REST APIs", "items": ["Django REST Framework", "Serializers", "ViewSets", "Authentication"]},
        ],
    },
    {
        "title": "Data Science Essentials",
        "category": "data_science",
        "difficulty": "intermediate",
        "description": "Master data analysis with Python. Learn pandas, numpy, matplotlib, and machine learning basics.",
        "objectives": ["Analyze datasets", "Create visualizations", "Build ML models"],
        "modules": [
            {"title": "Data Analysis with Pandas", "items": ["DataFrames", "Data Cleaning", "Aggregations", "Merging Data"]},
            {"title": "Data Visualization", "items": ["Matplotlib Basics", "Seaborn", "Interactive Plots", "Dashboard Design"]},
            {"title": "Machine Learning Intro", "items": ["Scikit-learn", "Regression", "Classification", "Model Evaluation"]},
        ],
    },
    {
        "title": "Project Management Professional",
        "category": "business",
        "difficulty": "advanced",
        "description": "Comprehensive project management course covering Agile, Scrum, and traditional methodologies.",
        "objectives": ["Lead project teams", "Manage budgets and timelines", "Apply Agile methodologies"],
        "modules": [
            {"title": "PM Fundamentals", "items": ["Project Lifecycle", "Stakeholder Management", "Scope Definition", "WBS"]},
            {"title": "Agile & Scrum", "items": ["Agile Manifesto", "Scrum Framework", "Sprint Planning", "Retrospectives"]},
            {"title": "Risk & Quality", "items": ["Risk Identification", "Risk Mitigation", "Quality Planning", "QA Processes"]},
        ],
    },
    {
        "title": "Digital Marketing Mastery",
        "category": "marketing",
        "difficulty": "beginner",
        "description": "Learn modern digital marketing strategies including SEO, social media, content marketing, and analytics.",
        "objectives": ["Create marketing campaigns", "Analyze marketing data", "Optimize conversions"],
        "modules": [
            {"title": "SEO Fundamentals", "items": ["Keyword Research", "On-page SEO", "Link Building", "Technical SEO"]},
            {"title": "Social Media Marketing", "items": ["Platform Strategy", "Content Calendar", "Engagement", "Paid Ads"]},
            {"title": "Analytics & Optimization", "items": ["Google Analytics", "Conversion Tracking", "A/B Testing", "Reporting"]},
        ],
    },
    {
        "title": "Cloud Computing with AWS",
        "category": "cloud",
        "difficulty": "intermediate",
        "description": "Master Amazon Web Services. Learn EC2, S3, Lambda, and cloud architecture best practices.",
        "objectives": ["Deploy to AWS", "Design scalable architectures", "Optimize cloud costs"],
        "modules": [
            {"title": "AWS Fundamentals", "items": ["AWS Console", "IAM", "EC2 Basics", "S3 Storage"]},
            {"title": "Serverless Computing", "items": ["Lambda Functions", "API Gateway", "DynamoDB", "Step Functions"]},
            {"title": "Architecture Patterns", "items": ["High Availability", "Auto Scaling", "Load Balancing", "Cost Optimization"]},
        ],
    },
]

LEARNER_GROUP_NAMES = [
    "2024 Cohort A",
    "2024 Cohort B", 
    "Engineering Team",
    "Marketing Team",
    "New Hires Q1",
]

PROMPT_TEMPLATES = [
    {
        "name": "Quiz Generator",
        "description": "Generate quiz questions from course content",
        "template": "Based on the following content, generate {num_questions} multiple choice questions:\n\n{content}\n\nFormat each question with 4 options (A-D) and indicate the correct answer.",
        "variables": ["num_questions", "content"],
    },
    {
        "name": "Content Summarizer",
        "description": "Summarize course content for quick review",
        "template": "Summarize the following content in {length} sentences, highlighting key concepts:\n\n{content}",
        "variables": ["length", "content"],
    },
    {
        "name": "Feedback Generator",
        "description": "Generate personalized feedback for student submissions",
        "template": "Provide constructive feedback for this student submission:\n\nAssignment: {assignment_title}\nSubmission: {submission}\nRubric: {rubric}\n\nInclude strengths, areas for improvement, and a grade recommendation.",
        "variables": ["assignment_title", "submission", "rubric"],
    },
    {
        "name": "Learning Path Recommender",
        "description": "Recommend next steps based on student progress",
        "template": "Based on the student's completed courses: {completed_courses}\nAnd their interests: {interests}\n\nRecommend the next 3 courses they should take and explain why.",
        "variables": ["completed_courses", "interests"],
    },
    {
        "name": "Discussion Prompt Creator",
        "description": "Create engaging discussion prompts for course forums",
        "template": "Create {num_prompts} thought-provoking discussion prompts for a course on {topic}. Each prompt should encourage critical thinking and peer interaction.",
        "variables": ["num_prompts", "topic"],
    },
]

NOTIFICATION_TYPES = [
    "COURSE_ENROLLED",
    "ASSIGNMENT_DUE",
    "GRADE_POSTED",
    "ANNOUNCEMENT",
    "CERTIFICATE_ISSUED",
]


class Command(BaseCommand):
    help = "Seeds the database with comprehensive demo data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing data before seeding",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("\n" + "=" * 60))
        self.stdout.write(self.style.SUCCESS("LMS Database Seeding"))
        self.stdout.write(self.style.SUCCESS("=" * 60 + "\n"))

        if options["clear"]:
            self._clear_data()

        with transaction.atomic():
            self._seed_all()

        self.stdout.write(self.style.SUCCESS("\n" + "=" * 60))
        self.stdout.write(self.style.SUCCESS("Seeding Complete!"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self._print_credentials()

    def _clear_data(self):
        """Clear existing demo data."""
        self.stdout.write(self.style.WARNING("\nClearing existing data..."))
        
        from apps.analytics.models import (
            Event, Report, InstructorAnalytics, StudentEngagementMetric,
            CourseAnalytics, PredictiveAnalytics, AIInsights, RealTimeMetrics,
            SocialLearningMetrics, DiscussionInteraction, PeerReview,
            CollaborativeProject, StudyGroup, StudentPerformance,
            LearningEfficiency, RevenueAnalytics
        )
        from apps.ai_engine.models import GenerationJob, PromptTemplate, ModelConfig
        from apps.notifications.models import Notification, Announcement
        from apps.learning_paths.models import LearningPathStepProgress, LearningPathProgress, LearningPathStep, LearningPath
        from apps.enrollments.models import Certificate, LearnerProgress, Enrollment
        from apps.assessments.models import AssessmentAttempt, Question, Assessment
        from apps.courses.models import ContentItem, Module, Course
        from apps.files.models import File, Folder
        from apps.users.models import LearnerGroup
        from apps.core.models import PlatformSettings, TenantDomain, Tenant

        # Delete in reverse dependency order
        # Social learning models first
        StudyGroup.objects.all().delete()
        CollaborativeProject.objects.all().delete()
        PeerReview.objects.all().delete()
        DiscussionInteraction.objects.all().delete()
        SocialLearningMetrics.objects.all().delete()
        # New analytics models
        StudentPerformance.objects.all().delete()
        LearningEfficiency.objects.all().delete()
        RevenueAnalytics.objects.all().delete()
        # Analytics models
        RealTimeMetrics.objects.all().delete()
        AIInsights.objects.all().delete()
        PredictiveAnalytics.objects.all().delete()
        CourseAnalytics.objects.all().delete()
        StudentEngagementMetric.objects.all().delete()
        InstructorAnalytics.objects.all().delete()
        Report.objects.all().delete()
        Event.objects.all().delete()
        GenerationJob.objects.all().delete()
        PromptTemplate.objects.all().delete()
        ModelConfig.objects.all().delete()
        Notification.objects.all().delete()
        Announcement.objects.all().delete()
        LearningPathStepProgress.objects.all().delete()
        LearningPathProgress.objects.all().delete()
        LearningPathStep.objects.all().delete()
        LearningPath.objects.all().delete()
        Certificate.objects.all().delete()
        LearnerProgress.objects.all().delete()
        Enrollment.objects.all().delete()
        AssessmentAttempt.objects.all().delete()
        Question.objects.all().delete()
        Assessment.objects.all().delete()
        ContentItem.objects.all().delete()
        Module.objects.all().delete()
        Course.objects.all().delete()
        File.objects.all().delete()
        Folder.objects.all().delete()
        # Clear tenant from all users first (some superusers might have tenant set)
        User.objects.filter(tenant__isnull=False).update(tenant=None)
        User.objects.filter(is_superuser=False).delete()
        LearnerGroup.objects.all().delete()
        PlatformSettings.objects.all().delete()
        TenantDomain.objects.all().delete()
        Tenant.objects.all().delete()

        self.stdout.write(self.style.SUCCESS("Data cleared."))

    def _seed_all(self):
        """Main seeding orchestration."""
        # 1. Core Infrastructure
        self._create_superuser()
        tenants = self._create_tenants()
        self._create_platform_settings(tenants)
        
        # 2. System-wide Report Definitions (created once, not per-tenant)
        self._create_reports()

        for tenant in tenants:
            self.stdout.write(f"\n--- Seeding {tenant.name} ---\n")
            
            # 2. Users & Groups
            users = self._create_users(tenant)
            admin = users["admin"]
            instructors = users["instructors"]
            learners = users["learners"]
            groups = self._create_learner_groups(tenant, learners)

            # 3. Files & Folders
            folders = self._create_folders(tenant, admin)

            # 4. Courses & Content
            courses = self._create_courses(tenant, instructors)
            
            # 5. Assessments
            self._create_assessments(courses)

            # 6. Enrollments & Progress
            enrollments = self._create_enrollments(learners, courses, groups)
            self._create_learner_progress(enrollments)
            self._create_assessment_attempts(enrollments)
            self._create_certificates(enrollments)

            # 7. Learning Paths
            learning_paths = self._create_learning_paths(tenant, courses)
            self._create_learning_path_progress(learning_paths, learners)

            # 8. AI Engine
            self._create_ai_configs(tenant)
            self._create_prompt_templates(tenant)

            # 9. Notifications & Announcements
            self._create_notifications(learners, courses)
            self._create_announcements(tenant, admin, courses)

            # 10. Analytics Events & Reports
            self._create_analytics_events(tenant, learners, courses)
            self._create_instructor_analytics(tenant, instructors, courses)
            self._create_student_engagement_metrics(tenant, learners, courses)
            self._create_course_analytics(tenant, courses)
            self._create_predictive_analytics(tenant, instructors)
            self._create_ai_insights(tenant, instructors)
            self._create_realtime_metrics(tenant, instructors)

            # 11. Social Learning Data
            self._create_social_learning_metrics(tenant, instructors, courses)
            self._create_discussion_interactions(tenant, learners, courses)
            self._create_peer_reviews(tenant, learners, courses)
            self._create_collaborative_projects(tenant, learners, courses)
            self._create_study_groups(tenant, learners, courses)

            # 12. Additional Analytics Data (for instructor analytics cards)
            self._create_student_performance(tenant, learners, courses)
            self._create_learning_efficiency(tenant, instructors, courses)
            self._create_revenue_analytics(tenant, courses)

    def _create_superuser(self):
        """Create superuser if not exists."""
        if User.objects.filter(is_superuser=True).exists():
            self.stdout.write("Superuser already exists.")
            return

        User.objects.create_superuser(
            email="admin@lms.local",
            password=DEFAULT_PASSWORD,
            first_name="Super",
            last_name="Admin",
        )
        self.stdout.write(self.style.SUCCESS("Created superuser: admin@lms.local"))

    def _create_tenants(self):
        """Create tenants with domains."""
        from apps.core.models import Tenant, TenantDomain

        tenants = []
        for config in TENANT_CONFIGS:
            tenant, created = Tenant.objects.get_or_create(
                slug=config["slug"],
                defaults={
                    "name": config["name"],
                    "is_active": True,
                    "theme_config": config["theme"],
                    "feature_flags": {
                        "ai_enabled": True,
                        "certificates_enabled": True,
                        "learning_paths_enabled": True,
                    },
                },
            )
            if created:
                TenantDomain.objects.create(
                    tenant=tenant,
                    domain=config["domain"],
                    is_primary=True,
                )
                self.stdout.write(f"Created tenant: {tenant.name}")
            tenants.append(tenant)
        return tenants

    def _create_platform_settings(self, tenants):
        """Create platform settings for each tenant."""
        from apps.core.models import PlatformSettings

        # Global settings
        PlatformSettings.objects.get_or_create(
            tenant=None,
            defaults={
                "site_name": "LMS Platform",
                "site_description": "Enterprise Learning Management System",
                "default_language": "en",
                "timezone": "UTC",
                "support_email": "support@lms.local",
                "max_file_size_mb": 100,
                "allowed_extensions": ["pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "mp4", "mp3", "png", "jpg", "jpeg", "gif"],
            },
        )

        for tenant in tenants:
            PlatformSettings.objects.get_or_create(
                tenant=tenant,
                defaults={
                    "site_name": tenant.name,
                    "site_description": f"Learning portal for {tenant.name}",
                    "support_email": f"support@{tenant.slug}.local",
                },
            )
        self.stdout.write("Created platform settings.")

    def _create_users(self, tenant):
        """Create users for a tenant."""
        users = {"admin": None, "instructors": [], "learners": []}

        # Tenant Admin
        admin_email = f"admin@{tenant.slug}.local"
        admin, created = User.objects.get_or_create(
            email=admin_email,
            defaults={
                "first_name": "Admin",
                "last_name": tenant.name.split()[0],
                "role": User.Role.ADMIN,
                "status": User.Status.ACTIVE,
                "tenant": tenant,
            },
        )
        if created:
            admin.set_password(DEFAULT_PASSWORD)
            admin.save()
        users["admin"] = admin

        # Instructors
        instructor_names = [
            ("John", "Smith"),
            ("Sarah", "Johnson"),
            ("Michael", "Chen"),
        ]
        for first, last in instructor_names:
            email = f"{first.lower()}.{last.lower()}@{tenant.slug}.local"
            instructor, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "role": User.Role.INSTRUCTOR,
                    "status": User.Status.ACTIVE,
                    "tenant": tenant,
                },
            )
            if created:
                instructor.set_password(DEFAULT_PASSWORD)
                instructor.save()
            users["instructors"].append(instructor)

        # Learners
        learner_names = [
            ("Alice", "Williams"),
            ("Bob", "Brown"),
            ("Carol", "Davis"),
            ("David", "Miller"),
            ("Emma", "Wilson"),
            ("Frank", "Moore"),
            ("Grace", "Taylor"),
            ("Henry", "Anderson"),
            ("Ivy", "Thomas"),
            ("Jack", "Jackson"),
            ("Kate", "White"),
            ("Leo", "Harris"),
        ]
        for first, last in learner_names:
            email = f"{first.lower()}.{last.lower()}@{tenant.slug}.local"
            learner, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "role": User.Role.LEARNER,
                    "status": User.Status.ACTIVE,
                    "tenant": tenant,
                },
            )
            if created:
                learner.set_password(DEFAULT_PASSWORD)
                learner.save()
            users["learners"].append(learner)

        self.stdout.write(f"Created {1 + len(users['instructors']) + len(users['learners'])} users.")
        return users

    def _create_learner_groups(self, tenant, learners):
        """Create learner groups and assign members."""
        from apps.users.models import LearnerGroup

        groups = []
        for i, name in enumerate(LEARNER_GROUP_NAMES[:3]):
            group, created = LearnerGroup.objects.get_or_create(
                tenant=tenant,
                name=name,
                defaults={"description": f"Group for {name}"},
            )
            if created:
                # Assign some learners to group
                group_learners = learners[i * 4 : (i + 1) * 4]
                group.members.set(group_learners)
            groups.append(group)

        self.stdout.write(f"Created {len(groups)} learner groups.")
        return groups

    def _create_folders(self, tenant, admin):
        """Create folder structure for files."""
        from apps.files.models import Folder

        folder_names = ["Course Materials", "Uploads", "Videos", "Documents"]
        folders = []
        for name in folder_names:
            folder, _ = Folder.objects.get_or_create(
                tenant=tenant,
                name=name,
                parent=None,
            )
            folders.append(folder)

        self.stdout.write(f"Created {len(folders)} folders.")
        return folders

    def _create_courses(self, tenant, instructors):
        """Create courses with modules and content items."""
        from apps.courses.models import Course, Module, ContentItem
        from apps.common.utils import generate_unique_slug

        courses = []
        for i, data in enumerate(COURSE_DATA):
            instructor = instructors[i % len(instructors)]
            
            # Determine status - make most courses published
            status = Course.Status.PUBLISHED if i < 5 else Course.Status.DRAFT

            course, created = Course.objects.get_or_create(
                tenant=tenant,
                title=data["title"],
                defaults={
                    "description": data["description"],
                    "instructor": instructor,
                    "status": status,
                    "category": data["category"],
                    "difficulty_level": data["difficulty"],
                    "estimated_duration": random.randint(10, 40) * 60,  # In minutes
                    "learning_objectives": data["objectives"],
                    "is_free": random.choice([True, False]),
                    "price": Decimal(random.choice(["0.00", "29.99", "49.99", "99.99"])),
                },
            )

            if created and not course.slug:
                course.slug = generate_unique_slug(course, source_field="title")
                course.save()

            # Create modules and content items
            for m_idx, module_data in enumerate(data["modules"], start=1):
                module, _ = Module.objects.get_or_create(
                    course=course,
                    order=m_idx,
                    defaults={
                        "title": module_data["title"],
                        "description": f"Learn about {module_data['title'].lower()}.",
                    },
                )

                for c_idx, item_title in enumerate(module_data["items"], start=1):
                    content_type = random.choice([
                        ContentItem.ContentType.TEXT,
                        ContentItem.ContentType.VIDEO,
                        ContentItem.ContentType.URL,
                    ])
                    
                    defaults = {
                        "title": item_title,
                        "content_type": content_type,
                        "is_published": status == Course.Status.PUBLISHED,
                        "is_required": c_idx <= 2,  # First 2 items are required
                    }
                    
                    if content_type == ContentItem.ContentType.TEXT:
                        defaults["text_content"] = f"""# {item_title}

This lesson covers {item_title.lower()} in detail.

## Key Concepts

- Concept 1: Understanding the basics
- Concept 2: Practical applications  
- Concept 3: Best practices

## Summary

In this lesson, you learned about {item_title.lower()}. Make sure to complete the practice exercises before moving on.
"""
                    elif content_type == ContentItem.ContentType.VIDEO:
                        defaults["external_url"] = f"https://www.youtube.com/watch?v={uuid.uuid4().hex[:11]}"
                    else:
                        defaults["external_url"] = f"https://docs.example.com/{course.slug}/{m_idx}/{c_idx}"

                    ContentItem.objects.get_or_create(
                        module=module,
                        order=c_idx,
                        defaults=defaults,
                    )

            courses.append(course)

        self.stdout.write(f"Created {len(courses)} courses with modules and content.")
        return courses

    def _create_assessments(self, courses):
        """Create assessments with questions for courses."""
        from apps.assessments.models import Assessment, Question

        for course in courses:
            # Create a quiz for each course
            assessment, created = Assessment.objects.get_or_create(
                course=course,
                assessment_type=Assessment.AssessmentType.QUIZ,
                defaults={
                    "title": f"{course.title} - Final Quiz",
                    "description": "Test your knowledge of the course material.",
                    "is_published": course.status == course.Status.PUBLISHED,
                    "grading_type": Assessment.GradingType.AUTO,
                    "pass_mark_percentage": 70,
                    "time_limit_minutes": 30,
                    "max_attempts": 3,
                    "show_results_immediately": True,
                    "shuffle_questions": True,
                },
            )

            if created:
                # Create questions
                question_templates = [
                    ("What is the main purpose of {topic}?", ["To improve efficiency", "To reduce costs", "To enhance quality", "All of the above"]),
                    ("Which of the following is NOT a feature of {topic}?", ["Feature A", "Feature B", "Feature C", "Feature X"]),
                    ("When should you use {topic}?", ["Always", "Never", "When appropriate", "Only in production"]),
                    ("What is a best practice for {topic}?", ["Practice A", "Practice B", "Practice C", "Practice D"]),
                    ("How does {topic} improve workflow?", ["By automation", "By documentation", "By testing", "By monitoring"]),
                ]

                topic = course.title.split()[0]
                for i, (q_text, options) in enumerate(question_templates, start=1):
                    correct_idx = random.randint(0, 3)
                    Question.objects.create(
                        assessment=assessment,
                        order=i,
                        question_type=Question.QuestionType.MULTIPLE_CHOICE,
                        question_text=q_text.format(topic=topic),
                        points=2,
                        type_specific_data={
                            "options": [
                                {"id": str(uuid.uuid4()), "text": opt, "is_correct": idx == correct_idx}
                                for idx, opt in enumerate(options)
                            ],
                            "allow_multiple": False,
                        },
                        feedback=f"The correct answer demonstrates understanding of {topic}.",
                    )

        self.stdout.write(f"Created assessments with questions for {len(courses)} courses.")

    def _create_enrollments(self, learners, courses, groups):
        """Create enrollments for learners in courses."""
        from apps.enrollments.models import Enrollment, GroupEnrollment

        enrollments = []
        published_courses = [c for c in courses if c.status == c.Status.PUBLISHED]

        for learner in learners:
            # Enroll each learner in 2-4 random courses
            num_courses = random.randint(2, min(4, len(published_courses)))
            selected_courses = random.sample(published_courses, num_courses)

            for course in selected_courses:
                status = random.choices(
                    [Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED],
                    weights=[0.7, 0.3],
                )[0]
                
                enrollment, created = Enrollment.objects.get_or_create(
                    user=learner,
                    course=course,
                    defaults={
                        "status": status,
                        "enrolled_at": timezone.now() - timedelta(days=random.randint(1, 60)),
                        "progress": random.randint(20, 100) if status == Enrollment.Status.COMPLETED else random.randint(0, 80),
                    },
                )
                if created and status == Enrollment.Status.COMPLETED:
                    enrollment.completed_at = timezone.now() - timedelta(days=random.randint(1, 30))
                    enrollment.progress = 100
                    enrollment.save()
                enrollments.append(enrollment)

        # Group enrollments
        for group in groups:
            if published_courses:
                course = random.choice(published_courses)
                GroupEnrollment.objects.get_or_create(
                    group=group,
                    course=course,
                )

        self.stdout.write(f"Created {len(enrollments)} enrollments.")
        return enrollments

    def _create_learner_progress(self, enrollments):
        """Create progress records for enrolled learners."""
        from apps.enrollments.models import LearnerProgress
        from apps.courses.models import ContentItem

        progress_count = 0
        for enrollment in enrollments:
            content_items = ContentItem.objects.filter(
                module__course=enrollment.course,
                is_published=True,
            ).order_by("module__order", "order")

            total_items = content_items.count()
            if total_items == 0:
                continue

            # Calculate how many items should be completed based on enrollment progress
            items_to_complete = int(total_items * (enrollment.progress / 100))

            for i, item in enumerate(content_items):
                if i < items_to_complete:
                    status = LearnerProgress.Status.COMPLETED
                elif i == items_to_complete:
                    status = LearnerProgress.Status.IN_PROGRESS
                else:
                    status = LearnerProgress.Status.NOT_STARTED

                progress, created = LearnerProgress.objects.get_or_create(
                    enrollment=enrollment,
                    content_item=item,
                    defaults={"status": status},
                )
                
                if created and status == LearnerProgress.Status.COMPLETED:
                    progress.started_at = timezone.now() - timedelta(days=random.randint(2, 30))
                    progress.completed_at = progress.started_at + timedelta(minutes=random.randint(10, 60))
                    progress.save()
                    progress_count += 1

        self.stdout.write(f"Created {progress_count} progress records.")

    def _create_assessment_attempts(self, enrollments):
        """Create assessment attempts for enrolled learners."""
        from apps.assessments.models import Assessment, AssessmentAttempt, Question

        attempt_count = 0
        for enrollment in enrollments:
            if enrollment.progress < 50:
                continue  # Only create attempts for learners with decent progress

            assessments = Assessment.objects.filter(
                course=enrollment.course,
                is_published=True,
            )

            for assessment in assessments:
                questions = Question.objects.filter(assessment=assessment)
                if not questions.exists():
                    continue

                # Create 1-2 attempts
                num_attempts = random.randint(1, 2)
                for attempt_num in range(num_attempts):
                    score = random.randint(40, 100)
                    max_score = sum(q.points for q in questions)
                    actual_score = int(max_score * score / 100)

                    # Build answers
                    answers = {}
                    for q in questions:
                        if q.question_type == Question.QuestionType.MULTIPLE_CHOICE:
                            options = q.type_specific_data.get("options", [])
                            if options:
                                selected = random.choice(options)
                                answers[str(q.id)] = {"selected_option_id": selected["id"]}

                    attempt = AssessmentAttempt.objects.create(
                        assessment=assessment,
                        user=enrollment.user,
                        status=AssessmentAttempt.AttemptStatus.GRADED,
                        start_time=timezone.now() - timedelta(days=random.randint(1, 20)),
                        answers=answers,
                        score=actual_score,
                        max_score=max_score,
                        is_passed=score >= assessment.pass_mark_percentage,
                    )
                    attempt.end_time = attempt.start_time + timedelta(minutes=random.randint(10, 30))
                    attempt.graded_at = attempt.end_time
                    attempt.save()
                    attempt_count += 1

        self.stdout.write(f"Created {attempt_count} assessment attempts.")

    def _create_certificates(self, enrollments):
        """Create certificates for completed enrollments."""
        from apps.enrollments.models import Certificate, Enrollment

        cert_count = 0
        completed = [e for e in enrollments if e.status == Enrollment.Status.COMPLETED]

        for enrollment in completed:
            Certificate.objects.get_or_create(
                enrollment=enrollment,
                defaults={
                    "user": enrollment.user,
                    "course": enrollment.course,
                    "status": Certificate.Status.ISSUED,
                    "issued_at": enrollment.completed_at or timezone.now(),
                    "description": f"Certificate of completion for {enrollment.course.title}",
                },
            )
            cert_count += 1

        self.stdout.write(f"Created {cert_count} certificates.")

    def _create_learning_paths(self, tenant, courses):
        """Create learning paths with steps."""
        from apps.learning_paths.models import LearningPath, LearningPathStep
        from apps.common.utils import generate_unique_slug
        from django.contrib.contenttypes.models import ContentType

        course_ct = ContentType.objects.get_for_model(courses[0].__class__)
        
        path_configs = [
            {
                "title": "Web Development Career Path",
                "description": "Master web development from basics to advanced concepts.",
                "course_indices": [0, 1],  # Python, Django
            },
            {
                "title": "Data Professional Path",
                "description": "Become a data professional with Python and analytics skills.",
                "course_indices": [0, 2],  # Python, Data Science
            },
            {
                "title": "Business Skills Bundle",
                "description": "Essential business and marketing skills for professionals.",
                "course_indices": [3, 4],  # PM, Digital Marketing
            },
        ]

        learning_paths = []
        for config in path_configs:
            path, created = LearningPath.objects.get_or_create(
                tenant=tenant,
                title=config["title"],
                defaults={
                    "description": config["description"],
                    "status": LearningPath.Status.PUBLISHED,
                },
            )

            if created and not path.slug:
                path.slug = generate_unique_slug(path, source_field="title")
                path.save()

            # Create steps
            for order, course_idx in enumerate(config["course_indices"], start=1):
                if course_idx < len(courses):
                    LearningPathStep.objects.get_or_create(
                        learning_path=path,
                        order=order,
                        defaults={
                            "content_type": course_ct,
                            "object_id": courses[course_idx].id,
                            "is_required": True,
                        },
                    )

            learning_paths.append(path)

        self.stdout.write(f"Created {len(learning_paths)} learning paths.")
        return learning_paths

    def _create_learning_path_progress(self, learning_paths, learners):
        """Create progress records for learners in learning paths."""
        from apps.learning_paths.models import (
            LearningPathProgress,
            LearningPathStepProgress,
            LearningPathStep,
        )

        progress_count = 0
        for path in learning_paths:
            # Enroll some learners in each path
            selected_learners = random.sample(learners, min(5, len(learners)))
            steps = LearningPathStep.objects.filter(learning_path=path).order_by("order")

            for learner in selected_learners:
                status = random.choice([
                    LearningPathProgress.Status.NOT_STARTED,
                    LearningPathProgress.Status.IN_PROGRESS,
                    LearningPathProgress.Status.COMPLETED,
                ])

                path_progress, created = LearningPathProgress.objects.get_or_create(
                    user=learner,
                    learning_path=path,
                    defaults={
                        "status": status,
                        "current_step_order": random.randint(1, steps.count()) if status != LearningPathProgress.Status.NOT_STARTED else 1,
                    },
                )

                if created:
                    if status != LearningPathProgress.Status.NOT_STARTED:
                        path_progress.started_at = timezone.now() - timedelta(days=random.randint(5, 30))
                    if status == LearningPathProgress.Status.COMPLETED:
                        path_progress.completed_at = timezone.now() - timedelta(days=random.randint(1, 5))
                    path_progress.save()

                    # Create step progress
                    for step in steps:
                        if status == LearningPathProgress.Status.COMPLETED:
                            step_status = LearningPathStepProgress.Status.COMPLETED
                        elif step.order < path_progress.current_step_order:
                            step_status = LearningPathStepProgress.Status.COMPLETED
                        elif step.order == path_progress.current_step_order:
                            step_status = LearningPathStepProgress.Status.IN_PROGRESS
                        else:
                            step_status = LearningPathStepProgress.Status.NOT_STARTED

                        LearningPathStepProgress.objects.get_or_create(
                            user=learner,
                            learning_path_progress=path_progress,
                            step=step,
                            defaults={"status": step_status},
                        )

                progress_count += 1

        self.stdout.write(f"Created {progress_count} learning path progress records.")

    def _create_ai_configs(self, tenant):
        """Create AI model configurations."""
        from apps.ai_engine.models import ModelConfig, ModelProvider

        configs = [
            {
                "name": "GPT-4 (Primary)",
                "provider": ModelProvider.OPENAI,
                "model_id": "gpt-4",
                "is_active": True,
                "default_params": {"temperature": 0.7, "max_tokens": 2000},
            },
            {
                "name": "GPT-3.5 Turbo (Fast)",
                "provider": ModelProvider.OPENAI,
                "model_id": "gpt-3.5-turbo",
                "is_active": True,
                "default_params": {"temperature": 0.5, "max_tokens": 1000},
            },
        ]

        for config in configs:
            ModelConfig.objects.get_or_create(
                tenant=tenant,
                name=config["name"],
                defaults={
                    "provider": config["provider"],
                    "model_id": config["model_id"],
                    "is_active": config["is_active"],
                    "default_params": config["default_params"],
                    "api_key": "sk-demo-key-replace-in-production",
                },
            )

        self.stdout.write("Created AI model configurations.")

    def _create_prompt_templates(self, tenant):
        """Create AI prompt templates."""
        from apps.ai_engine.models import PromptTemplate

        for template in PROMPT_TEMPLATES:
            PromptTemplate.objects.get_or_create(
                tenant=tenant,
                name=template["name"],
                defaults={
                    "description": template["description"],
                    "template_text": template["template"],
                    "variables": template["variables"],
                },
            )

        self.stdout.write(f"Created {len(PROMPT_TEMPLATES)} prompt templates.")

    def _create_notifications(self, learners, courses):
        """Create notifications for learners."""
        from apps.notifications.models import Notification

        notification_count = 0
        for learner in learners[:6]:  # Create for first 6 learners
            # Course enrollment notification
            if courses:
                course = random.choice(courses)
                Notification.objects.create(
                    recipient=learner,
                    notification_type="COURSE_ENROLLED",
                    status=random.choice(["SENT", "READ"]),
                    subject=f"Welcome to {course.title}!",
                    message=f"You have been enrolled in {course.title}. Start learning today!",
                    action_url=f"/learner/courses/{course.slug}",
                    delivery_methods=["IN_APP", "EMAIL"],
                )
                notification_count += 1

            # Assignment due notification
            Notification.objects.create(
                recipient=learner,
                notification_type="ASSIGNMENT_DUE",
                status="SENT",
                subject="Assignment Due Soon",
                message="You have an assignment due in 3 days. Don't forget to submit!",
                action_url="/learner/assessments",
                delivery_methods=["IN_APP"],
            )
            notification_count += 1

        self.stdout.write(f"Created {notification_count} notifications.")

    def _create_announcements(self, tenant, admin, courses):
        """Create announcements."""
        from apps.notifications.models import Announcement

        announcements = [
            {
                "title": "Welcome to the Platform",
                "message": "Welcome to our learning platform! We're excited to have you here. Explore our courses and start your learning journey today.",
                "target_type": Announcement.TargetType.ALL_TENANT,
                "status": Announcement.Status.SENT,
            },
            {
                "title": "New Courses Available",
                "message": "We've added new courses to our catalog. Check them out and enroll today!",
                "target_type": Announcement.TargetType.ALL_TENANT,
                "status": Announcement.Status.SENT,
            },
            {
                "title": "System Maintenance Notice",
                "message": "The platform will undergo scheduled maintenance this weekend. Some features may be temporarily unavailable.",
                "target_type": Announcement.TargetType.ALL_TENANT,
                "status": Announcement.Status.DRAFT,
            },
        ]

        for data in announcements:
            Announcement.objects.get_or_create(
                tenant=tenant,
                title=data["title"],
                defaults={
                    "message": data["message"],
                    "author": admin,
                    "target_type": data["target_type"],
                    "status": data["status"],
                    "sent_at": timezone.now() if data["status"] == "SENT" else None,
                },
            )

        # Course-specific announcement
        if courses:
            course = courses[0]
            Announcement.objects.get_or_create(
                tenant=tenant,
                title=f"Important Update for {course.title}",
                defaults={
                    "message": f"New content has been added to {course.title}. Check it out!",
                    "author": admin,
                    "target_type": Announcement.TargetType.COURSE_ENROLLED,
                    "target_course": course,
                    "status": Announcement.Status.SENT,
                    "sent_at": timezone.now(),
                },
            )

        self.stdout.write(f"Created {len(announcements) + 1} announcements.")

    def _create_analytics_events(self, tenant, learners, courses):
        """Create analytics events."""
        from apps.analytics.models import Event

        # Event types are plain strings matching EVENT_TYPES tuples
        event_types = [
            "USER_LOGIN",
            "COURSE_VIEW",
            "CONTENT_VIEW",
            "MODULE_VIEW",
            "ASSESSMENT_START",
            "ASSESSMENT_SUBMIT",
        ]

        event_count = 0
        for learner in learners[:8]:  # Events for first 8 learners
            for _ in range(random.randint(10, 25)):
                event_type = random.choice(event_types)
                course = random.choice(courses) if courses else None

                context_data = {"user_agent": "Mozilla/5.0", "device_type": random.choice(["desktop", "mobile", "tablet"])}
                if course:
                    context_data["course_id"] = str(course.id)
                    context_data["course_title"] = course.title

                Event.objects.create(
                    tenant=tenant,
                    user=learner,
                    event_type=event_type,
                    timestamp=timezone.now() - timedelta(
                        days=random.randint(0, 30),
                        hours=random.randint(0, 23),
                        minutes=random.randint(0, 59),
                    ),
                    context_data=context_data,
                    session_id=str(uuid.uuid4()),
                    device_type=context_data["device_type"],
                    browser=random.choice(["Chrome", "Firefox", "Safari", "Edge"]),
                    os=random.choice(["Windows", "macOS", "Linux", "iOS", "Android"]),
                )
                event_count += 1

        self.stdout.write(f"Created {event_count} analytics events.")

    def _create_reports(self):
        """Create system-wide report definitions matching ReportGeneratorService slugs."""
        from apps.analytics.models import Report

        report_definitions = [
            {
                "name": "Course Completion Rates",
                "slug": "course-completion-rates",
                "description": "Shows completion rates across courses with enrollment and completion statistics.",
                "config": {"report_type": "completion", "grouping": "course"},
            },
            {
                "name": "User Activity Summary",
                "slug": "user-activity-summary",
                "description": "Summarizes user activity including logins, course views, and content interactions.",
                "config": {"report_type": "activity", "grouping": "user"},
            },
            {
                "name": "Assessment Results",
                "slug": "assessment-results",
                "description": "Displays assessment scores, pass rates, and attempt statistics.",
                "config": {"report_type": "assessment", "include_scores": True},
            },
            {
                "name": "Student Progress",
                "slug": "student-progress",
                "description": "Tracks individual student progress through courses and learning paths.",
                "config": {"report_type": "progress", "grouping": "student"},
            },
            {
                "name": "Instructor Dashboard",
                "slug": "instructor-dashboard",
                "description": "Comprehensive dashboard for instructors showing course and student metrics.",
                "config": {"report_type": "dashboard", "role": "instructor"},
            },
            {
                "name": "Student Engagement",
                "slug": "student-engagement",
                "description": "Analyzes student engagement metrics including time spent, interactions, and activity patterns.",
                "config": {"report_type": "engagement", "metrics": ["time", "interactions", "patterns"]},
            },
            {
                "name": "Course Performance",
                "slug": "course-performance",
                "description": "Detailed course performance analytics including enrollment, completion, and revenue.",
                "config": {"report_type": "performance", "grouping": "course"},
            },
            {
                "name": "Predictive Insights",
                "slug": "predictive-insights",
                "description": "AI-powered predictive analytics showing at-risk students and forecasting.",
                "config": {"report_type": "predictive", "include_forecasting": True},
            },
            {
                "name": "AI Recommendations",
                "slug": "ai-recommendations",
                "description": "AI-generated insights and recommendations for improving learning outcomes.",
                "config": {"report_type": "ai", "include_recommendations": True},
            },
            {
                "name": "Real-Time Metrics",
                "slug": "real-time-metrics",
                "description": "Live dashboard showing current active users, sessions, and engagement.",
                "config": {"report_type": "realtime", "refresh_interval": 30},
            },
        ]

        for report_def in report_definitions:
            Report.objects.get_or_create(
                slug=report_def["slug"],
                defaults={
                    "tenant": None,  # System-wide report
                    "name": report_def["name"],
                    "description": report_def["description"],
                    "config": report_def["config"],
                },
            )

        self.stdout.write(f"Created {len(report_definitions)} report definitions.")

    def _create_instructor_analytics(self, tenant, instructors, courses):
        """Create instructor analytics records."""
        from apps.analytics.models import InstructorAnalytics

        today = timezone.now().date()
        
        for instructor in instructors:
            instructor_courses = [c for c in courses if c.instructor == instructor]
            published_count = len([c for c in instructor_courses if c.status == c.Status.PUBLISHED])
            
            InstructorAnalytics.objects.get_or_create(
                tenant=tenant,
                instructor_id=instructor.id,
                date=today,
                defaults={
                    "total_courses": len(instructor_courses),
                    "published_courses": published_count,
                    "draft_courses": len(instructor_courses) - published_count,
                    "total_students": random.randint(20, 100),
                    "active_students": random.randint(10, 50),
                    "new_students": random.randint(2, 15),
                    "avg_course_rating": Decimal(str(round(random.uniform(3.5, 5.0), 2))),
                    "avg_completion_rate": Decimal(str(round(random.uniform(40, 85), 2))),
                    "avg_engagement_rate": Decimal(str(round(random.uniform(50, 90), 2))),
                    "total_revenue": Decimal(str(random.randint(1000, 50000))),
                    "monthly_revenue": Decimal(str(random.randint(500, 10000))),
                    "avg_revenue_per_student": Decimal(str(round(random.uniform(25, 150), 2))),
                    "student_growth_rate": Decimal(str(round(random.uniform(-5, 20), 2))),
                    "revenue_growth_rate": Decimal(str(round(random.uniform(-10, 30), 2))),
                    "pending_grading": random.randint(0, 15),
                    "total_enrollments": random.randint(30, 150),
                    "active_enrollments": random.randint(15, 80),
                    "modules_created": random.randint(10, 50),
                    "content_items_created": random.randint(30, 200),
                    "published_this_month": random.randint(0, 5),
                },
            )

        self.stdout.write(f"Created instructor analytics for {len(instructors)} instructors.")

    def _create_student_engagement_metrics(self, tenant, learners, courses):
        """Create student engagement metrics."""
        from apps.analytics.models import StudentEngagementMetric

        today = timezone.now().date()
        metrics_count = 0
        
        for learner in learners[:8]:  # Metrics for first 8 learners
            for course in random.sample(courses[:5], min(3, len(courses))):
                StudentEngagementMetric.objects.get_or_create(
                    tenant=tenant,
                    user=learner,
                    course_id=course.id,
                    date=today,
                    defaults={
                        "daily_active_time": random.randint(10, 120),
                        "weekly_active_time": random.randint(60, 600),
                        "monthly_active_time": random.randint(200, 2000),
                        "content_views": random.randint(5, 50),
                        "video_watches": random.randint(2, 20),
                        "quiz_attempts": random.randint(1, 10),
                        "discussion_posts": random.randint(0, 15),
                        "assignments_submitted": random.randint(0, 5),
                        "avg_quiz_score": Decimal(str(round(random.uniform(50, 95), 2))),
                        "completion_rate": Decimal(str(round(random.uniform(10, 100), 2))),
                        "session_count": random.randint(5, 30),
                        "avg_session_duration": random.randint(15, 90),
                        "last_activity_date": timezone.now() - timedelta(days=random.randint(0, 7)),
                        "risk_score": Decimal(str(round(random.uniform(0, 50), 2))),
                        "risk_factors": random.choice([None, ["low_engagement"], ["missed_deadlines"], ["declining_scores"]]),
                        "preferred_learning_time": random.choice(["morning", "afternoon", "evening"]),
                        "preferred_device": random.choice(["desktop", "mobile", "tablet"]),
                        "preferred_content_type": random.choice(["video", "text", "interactive"]),
                    },
                )
                metrics_count += 1

        self.stdout.write(f"Created {metrics_count} student engagement metrics.")

    def _create_course_analytics(self, tenant, courses):
        """Create course analytics records."""
        from apps.analytics.models import CourseAnalytics

        today = timezone.now().date()
        
        for course in courses:
            if course.status != course.Status.PUBLISHED:
                continue
                
            CourseAnalytics.objects.get_or_create(
                tenant=tenant,
                course_id=course.id,
                date=today,
                defaults={
                    "instructor_id": course.instructor.id,
                    "total_enrollments": random.randint(20, 150),
                    "active_enrollments": random.randint(10, 80),
                    "completed_enrollments": random.randint(5, 40),
                    "dropped_enrollments": random.randint(0, 10),
                    "avg_completion_rate": Decimal(str(round(random.uniform(40, 85), 2))),
                    "avg_engagement_score": Decimal(str(round(random.uniform(50, 90), 2))),
                    "avg_rating": Decimal(str(round(random.uniform(3.5, 5.0), 2))),
                    "total_reviews": random.randint(5, 50),
                    "total_revenue": Decimal(str(random.randint(500, 20000))),
                    "avg_revenue_per_student": Decimal(str(round(random.uniform(20, 100), 2))),
                    "total_content_items": random.randint(10, 50),
                    "avg_content_completion_rate": Decimal(str(round(random.uniform(40, 90), 2))),
                    "most_viewed_content": [{"title": "Introduction", "views": random.randint(50, 200)}],
                    "least_viewed_content": [{"title": "Advanced Topics", "views": random.randint(5, 30)}],
                    "total_assessments": random.randint(1, 5),
                    "avg_assessment_score": Decimal(str(round(random.uniform(60, 85), 2))),
                    "assessment_completion_rate": Decimal(str(round(random.uniform(50, 95), 2))),
                    "discussion_messages": random.randint(10, 100),
                    "discussion_participants": random.randint(5, 30),
                    "peer_reviews": random.randint(0, 20),
                    "collaborative_projects": random.randint(0, 5),
                    "avg_time_to_complete": random.randint(7, 60),
                    "avg_study_time_per_week": random.randint(60, 300),
                    "device_distribution": {"desktop": 60, "mobile": 30, "tablet": 10},
                    "geographic_distribution": {"North America": 40, "Europe": 30, "Asia": 20, "Other": 10},
                },
            )

        self.stdout.write(f"Created course analytics for {len([c for c in courses if c.status == c.Status.PUBLISHED])} courses.")

    def _create_predictive_analytics(self, tenant, instructors):
        """Create predictive analytics records."""
        from apps.analytics.models import PredictiveAnalytics

        today = timezone.now().date()
        
        for instructor in instructors:
            PredictiveAnalytics.objects.get_or_create(
                tenant=tenant,
                instructor_id=instructor.id,
                prediction_date=today,
                defaults={
                    "students_at_risk": [
                        {"student_id": str(uuid.uuid4()), "risk_level": "high", "factors": ["low_engagement", "missed_deadlines"]},
                        {"student_id": str(uuid.uuid4()), "risk_level": "medium", "factors": ["declining_scores"]},
                    ],
                    "course_recommendations": [
                        {"action": "Add more video content", "impact": "high", "confidence": 0.85},
                        {"action": "Increase quiz frequency", "impact": "medium", "confidence": 0.72},
                    ],
                    "revenue_forecast": {
                        "next_month": random.randint(5000, 20000),
                        "next_quarter": random.randint(15000, 60000),
                        "confidence": round(random.uniform(0.7, 0.95), 2),
                    },
                    "trends_analysis": {
                        "enrollment_trend": random.choice(["increasing", "stable", "decreasing"]),
                        "engagement_trend": random.choice(["improving", "stable", "declining"]),
                        "completion_trend": random.choice(["improving", "stable", "declining"]),
                    },
                    "prediction_confidence": Decimal(str(round(random.uniform(70, 95), 2))),
                    "model_version": "1.0",
                },
            )

        self.stdout.write(f"Created predictive analytics for {len(instructors)} instructors.")

    def _create_ai_insights(self, tenant, instructors):
        """Create AI insights records."""
        from apps.analytics.models import AIInsights

        today = timezone.now().date()
        
        for instructor in instructors:
            AIInsights.objects.get_or_create(
                tenant=tenant,
                instructor_id=instructor.id,
                date=today,
                defaults={
                    "key_insights": [
                        {"type": "positive", "message": "Student engagement increased 15% this week", "priority": "high"},
                        {"type": "warning", "message": "3 students showing signs of disengagement", "priority": "medium"},
                        {"type": "neutral", "message": "Course completion rate remains stable", "priority": "low"},
                    ],
                    "recommendations": [
                        {"action": "Schedule office hours for at-risk students", "expected_impact": "high"},
                        {"action": "Add discussion prompts to increase engagement", "expected_impact": "medium"},
                        {"action": "Consider adding recap videos for complex topics", "expected_impact": "medium"},
                    ],
                    "anomalies": [
                        {"type": "spike", "metric": "video_views", "description": "Unusual spike in video views on Module 3"},
                    ],
                    "confidence_score": Decimal(str(round(random.uniform(75, 95), 2))),
                    "ai_model": "gpt-4",
                    "model_version": "1.0",
                },
            )

        self.stdout.write(f"Created AI insights for {len(instructors)} instructors.")

    def _create_realtime_metrics(self, tenant, instructors):
        """Create real-time metrics records."""
        from apps.analytics.models import RealTimeMetrics

        for instructor in instructors:
            RealTimeMetrics.objects.create(
                tenant=tenant,
                instructor_id=instructor.id,
                active_users=random.randint(5, 50),
                current_sessions=random.randint(3, 30),
                live_engagement_rate=Decimal(str(round(random.uniform(40, 90), 2))),
                server_health=Decimal("100.00"),
                response_time=random.randint(50, 200),
                current_course_views=random.randint(10, 100),
                current_video_watches=random.randint(5, 40),
                current_quiz_attempts=random.randint(2, 20),
            )

        self.stdout.write(f"Created real-time metrics for {len(instructors)} instructors.")

    def _create_social_learning_metrics(self, tenant, instructors, courses):
        """Create social learning metrics records for the social tab."""
        from apps.analytics.models import SocialLearningMetrics

        today = timezone.now().date()
        metrics_count = 0

        for instructor in instructors:
            instructor_courses = [c for c in courses if c.instructor == instructor]
            
            for course in instructor_courses:
                if course.status != course.Status.PUBLISHED:
                    continue

                SocialLearningMetrics.objects.get_or_create(
                    tenant=tenant,
                    instructor_id=instructor.id,
                    course_id=course.id,
                    date=today,
                    defaults={
                        "discussion_messages": random.randint(10, 100),
                        "discussion_participants": random.randint(5, 30),
                        "discussion_threads": random.randint(3, 20),
                        "peer_reviews_submitted": random.randint(5, 25),
                        "peer_reviews_received": random.randint(5, 25),
                        "avg_peer_review_rating": Decimal(str(round(random.uniform(3.5, 5.0), 2))),
                        "collaborative_projects": random.randint(1, 5),
                        "project_participants": random.randint(5, 20),
                        "avg_project_completion_rate": Decimal(str(round(random.uniform(50, 95), 2))),
                        "study_groups": random.randint(1, 5),
                        "peer_help_requests": random.randint(5, 30),
                        "peer_help_responses": random.randint(3, 25),
                    },
                )
                metrics_count += 1

        self.stdout.write(f"Created {metrics_count} social learning metrics records.")

    def _create_discussion_interactions(self, tenant, learners, courses):
        """Create discussion interaction records for social learning analytics."""
        from apps.analytics.models import DiscussionInteraction

        interaction_types = ["post", "reply", "like", "view"]
        interaction_count = 0

        published_courses = [c for c in courses if c.status == c.Status.PUBLISHED]

        for learner in learners[:8]:  # Create interactions for first 8 learners
            selected_courses = random.sample(published_courses, min(3, len(published_courses)))
            
            for course in selected_courses:
                num_interactions = random.randint(2, 8)
                
                for _ in range(num_interactions):
                    interaction_type = random.choice(interaction_types)
                    discussion_id = str(uuid.uuid4())
                    
                    defaults = {
                        "interaction_type": interaction_type,
                        "discussion_id": discussion_id,
                        "content_length": random.randint(50, 500) if interaction_type in ["post", "reply"] else 0,
                        "likes_received": random.randint(0, 15) if interaction_type == "post" else 0,
                        "replies_received": random.randint(0, 8) if interaction_type == "post" else 0,
                        "quality_score": Decimal(str(round(random.uniform(50, 95), 2))) if interaction_type in ["post", "reply"] else None,
                        "helpfulness_rating": Decimal(str(round(random.uniform(3.0, 5.0), 2))) if interaction_type in ["post", "reply"] else None,
                    }
                    
                    if interaction_type == "reply":
                        defaults["post_id"] = str(uuid.uuid4())

                    DiscussionInteraction.objects.create(
                        tenant=tenant,
                        user=learner,
                        course=course,
                        **defaults,
                    )
                    interaction_count += 1

        self.stdout.write(f"Created {interaction_count} discussion interactions.")

    def _create_peer_reviews(self, tenant, learners, courses):
        """Create peer review records for social learning analytics."""
        from apps.analytics.models import PeerReview
        from apps.assessments.models import Assessment

        review_count = 0
        published_courses = [c for c in courses if c.status == c.Status.PUBLISHED]

        for course in published_courses:
            assessments = Assessment.objects.filter(course=course, is_published=True)
            if not assessments.exists():
                continue

            assessment = assessments.first()
            course_learners = list(learners[:8])
            
            # Create pairs of reviewers and reviewees
            for i in range(min(6, len(course_learners))):
                reviewer = course_learners[i]
                reviewee = course_learners[(i + 1) % len(course_learners)]
                
                if reviewer == reviewee:
                    continue

                assignment_id = str(uuid.uuid4())
                
                PeerReview.objects.create(
                    tenant=tenant,
                    reviewer=reviewer,
                    reviewee=reviewee,
                    course=course,
                    assessment=assessment,
                    assignment_id=assignment_id,
                    rating=Decimal(str(round(random.uniform(3.0, 5.0), 2))),
                    feedback=f"Great work on this assignment! I particularly liked your approach to the problem. Consider exploring more edge cases in your solution.",
                    feedback_quality=Decimal(str(round(random.uniform(60, 95), 2))),
                    helpfulness_rating=Decimal(str(round(random.uniform(3.5, 5.0), 2))),
                    status=random.choice(["submitted", "reviewed"]),
                    submitted_at=timezone.now() - timedelta(days=random.randint(1, 14)),
                )
                review_count += 1

        self.stdout.write(f"Created {review_count} peer reviews.")

    def _create_collaborative_projects(self, tenant, learners, courses):
        """Create collaborative project records for social learning analytics."""
        from apps.analytics.models import CollaborativeProject

        project_count = 0
        published_courses = [c for c in courses if c.status == c.Status.PUBLISHED]
        
        project_titles = [
            "Team Research Project",
            "Group Case Study",
            "Collaborative Presentation",
            "Peer Learning Exercise",
            "Joint Analysis Assignment",
        ]

        for course in published_courses[:4]:  # Create projects for first 4 courses
            num_projects = random.randint(1, 3)
            
            for i in range(num_projects):
                title = f"{course.title.split()[0]} {random.choice(project_titles)}"
                
                project = CollaborativeProject.objects.create(
                    tenant=tenant,
                    course=course,
                    title=title,
                    description=f"A collaborative project for {course.title} where team members work together to complete a comprehensive assignment.",
                    due_date=timezone.now() + timedelta(days=random.randint(7, 30)),
                    max_participants=random.randint(3, 5),
                    status=random.choice(["planning", "in_progress", "submitted", "completed"]),
                    total_contributions=random.randint(5, 30),
                    avg_participation_score=Decimal(str(round(random.uniform(60, 95), 2))),
                    completion_rate=Decimal(str(round(random.uniform(30, 100), 2))),
                )
                
                # Add participants
                num_participants = random.randint(2, 4)
                participants = random.sample(list(learners), min(num_participants, len(learners)))
                project.participants.set(participants)
                
                project_count += 1

        self.stdout.write(f"Created {project_count} collaborative projects.")

    def _create_study_groups(self, tenant, learners, courses):
        """Create study group records for social learning analytics."""
        from apps.analytics.models import StudyGroup

        group_count = 0
        published_courses = [c for c in courses if c.status == c.Status.PUBLISHED]
        
        group_names = [
            "Study Squad",
            "Learning Circle",
            "Peer Tutoring Group",
            "Discussion Group",
            "Practice Partners",
        ]

        for course in published_courses[:4]:  # Create groups for first 4 courses
            num_groups = random.randint(1, 2)
            
            for i in range(num_groups):
                name = f"{course.title.split()[0]} {random.choice(group_names)}"
                
                group = StudyGroup.objects.create(
                    tenant=tenant,
                    course=course,
                    name=name,
                    description=f"A study group for students enrolled in {course.title} to collaborate and help each other learn.",
                    max_members=random.randint(5, 10),
                    total_sessions=random.randint(3, 15),
                    avg_session_duration=timedelta(minutes=random.randint(30, 90)),
                    last_activity=timezone.now() - timedelta(days=random.randint(0, 7)),
                    is_active=True,
                )
                
                # Add members
                num_members = random.randint(3, 6)
                members = random.sample(list(learners), min(num_members, len(learners)))
                group.members.set(members)
                
                group_count += 1

        self.stdout.write(f"Created {group_count} study groups.")

    def _create_student_performance(self, tenant, learners, courses):
        """Create student performance records for at-risk students and top performers."""
        from apps.analytics.models import StudentPerformance
        from apps.assessments.models import Assessment

        performance_count = 0
        published_courses = [c for c in courses if c.status == c.Status.PUBLISHED]
        
        # Risk factors for at-risk students
        risk_factor_options = [
            ["low_engagement", "missed_deadlines"],
            ["declining_scores", "low_attendance"],
            ["incomplete_assignments", "low_quiz_scores"],
            ["irregular_login_pattern", "no_forum_participation"],
            ["low_video_completion", "skipped_modules"],
        ]

        for learner in learners:
            selected_courses = random.sample(published_courses, min(3, len(published_courses)))
            
            for course in selected_courses:
                # Get an assessment for the course if available
                assessment = Assessment.objects.filter(course=course, is_published=True).first()
                
                # Determine if this student is at-risk, average, or top performer
                performance_type = random.choices(
                    ["at_risk", "average", "top_performer"],
                    weights=[0.2, 0.5, 0.3]
                )[0]
                
                if performance_type == "at_risk":
                    score = Decimal(str(round(random.uniform(30, 55), 2)))
                    completion_rate = Decimal(str(round(random.uniform(10, 40), 2)))
                    risk_score = Decimal(str(round(random.uniform(60, 95), 2)))
                    risk_factors = random.choice(risk_factor_options)
                elif performance_type == "top_performer":
                    score = Decimal(str(round(random.uniform(85, 100), 2)))
                    completion_rate = Decimal(str(round(random.uniform(85, 100), 2)))
                    risk_score = Decimal(str(round(random.uniform(0, 15), 2)))
                    risk_factors = []
                else:  # average
                    score = Decimal(str(round(random.uniform(55, 85), 2)))
                    completion_rate = Decimal(str(round(random.uniform(40, 85), 2)))
                    risk_score = Decimal(str(round(random.uniform(15, 45), 2)))
                    risk_factors = []

                StudentPerformance.objects.get_or_create(
                    tenant=tenant,
                    student=learner,
                    course=course,
                    assessment=assessment,
                    defaults={
                        "score": score,
                        "completion_rate": completion_rate,
                        "time_spent": timedelta(hours=random.randint(5, 50)),
                        "completion_time": timedelta(hours=random.randint(10, 100)) if completion_rate > 80 else None,
                        "attempts": random.randint(1, 3),
                        "risk_score": risk_score,
                        "risk_factors": risk_factors,
                    },
                )
                performance_count += 1

        self.stdout.write(f"Created {performance_count} student performance records.")

    def _create_learning_efficiency(self, tenant, instructors, courses):
        """Create learning efficiency records for optimal study times and content effectiveness."""
        from apps.analytics.models import LearningEfficiency

        today = timezone.now().date()
        efficiency_count = 0
        
        # Generate optimal study times data (24 hours)
        def generate_optimal_study_times():
            times = []
            for hour in range(24):
                # Higher efficiency during typical study hours (0-100 scale)
                if 9 <= hour <= 12 or 14 <= hour <= 17 or 19 <= hour <= 22:
                    efficiency = round(random.uniform(60, 95), 1)
                elif 6 <= hour <= 8 or 13 <= hour <= 14 or 18 <= hour <= 19:
                    efficiency = round(random.uniform(40, 70), 1)
                else:
                    efficiency = round(random.uniform(10, 40), 1)
                times.append({"hour": hour, "efficiency": efficiency})
            return times

        # Generate content effectiveness data
        def generate_content_effectiveness():
            content_types = [
                {"contentType": "video", "avgTimeSpent": random.randint(15, 45), "completionRate": round(random.uniform(70, 95), 1)},
                {"contentType": "text", "avgTimeSpent": random.randint(10, 30), "completionRate": round(random.uniform(60, 90), 1)},
                {"contentType": "interactive", "avgTimeSpent": random.randint(20, 60), "completionRate": round(random.uniform(75, 98), 1)},
                {"contentType": "quiz", "avgTimeSpent": random.randint(10, 25), "completionRate": round(random.uniform(80, 100), 1)},
                {"contentType": "assignment", "avgTimeSpent": random.randint(30, 90), "completionRate": round(random.uniform(50, 85), 1)},
            ]
            return content_types

        # Generate difficulty progression data
        def generate_difficulty_progression():
            return [
                {"level": "beginner", "avgScore": round(random.uniform(75, 95), 1), "dropoffRate": round(random.uniform(5, 15), 1)},
                {"level": "intermediate", "avgScore": round(random.uniform(65, 85), 1), "dropoffRate": round(random.uniform(10, 25), 1)},
                {"level": "advanced", "avgScore": round(random.uniform(55, 75), 1), "dropoffRate": round(random.uniform(15, 35), 1)},
            ]

        for instructor in instructors:
            # Create one record per instructor (aggregate across all courses)
            LearningEfficiency.objects.get_or_create(
                tenant=tenant,
                instructor_id=instructor.id,
                course_id=None,  # Aggregate across all courses
                date=today,
                defaults={
                    "optimal_study_times": generate_optimal_study_times(),
                    "content_effectiveness": generate_content_effectiveness(),
                    "difficulty_progression": generate_difficulty_progression(),
                    "learning_patterns": {
                        "preferred_session_length": random.randint(25, 55),
                        "avg_sessions_per_week": round(random.uniform(3, 7), 1),
                        "most_active_day": random.choice(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]),
                    },
                },
            )
            efficiency_count += 1

            # Also create per-course records for the instructor's courses
            instructor_courses = [c for c in courses if c.instructor == instructor and c.status == c.Status.PUBLISHED]
            for course in instructor_courses[:3]:  # Limit to 3 courses per instructor
                LearningEfficiency.objects.get_or_create(
                    tenant=tenant,
                    instructor_id=instructor.id,
                    course_id=course.id,
                    date=today,
                    defaults={
                        "optimal_study_times": generate_optimal_study_times(),
                        "content_effectiveness": generate_content_effectiveness(),
                        "difficulty_progression": generate_difficulty_progression(),
                        "learning_patterns": {
                            "preferred_session_length": random.randint(25, 55),
                            "avg_sessions_per_week": round(random.uniform(3, 7), 1),
                            "most_active_day": random.choice(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]),
                        },
                    },
                )
                efficiency_count += 1

        self.stdout.write(f"Created {efficiency_count} learning efficiency records.")

    def _create_revenue_analytics(self, tenant, courses):
        """Create revenue analytics records for revenue by course card."""
        from apps.analytics.models import RevenueAnalytics

        today = timezone.now().date()
        revenue_count = 0
        published_courses = [c for c in courses if c.status == c.Status.PUBLISHED]

        # Create monthly revenue data for the past 6 months
        for i in range(6):
            period_end = today - timedelta(days=i * 30)
            period_start = period_end - timedelta(days=30)
            
            for course in published_courses:
                enrolled_students = random.randint(10, 100)
                # Use course price or generate random price
                price_per_student = float(course.price) if course.price and float(course.price) > 0 else random.uniform(29.99, 149.99)
                total_revenue = Decimal(str(round(enrolled_students * price_per_student, 2)))
                revenue_per_student = Decimal(str(round(price_per_student, 2)))
                
                RevenueAnalytics.objects.get_or_create(
                    tenant=tenant,
                    course=course,
                    period_start=period_start,
                    period_end=period_end,
                    defaults={
                        "instructor": course.instructor,
                        "total_revenue": total_revenue,
                        "enrolled_students": enrolled_students,
                        "revenue_per_student": revenue_per_student,
                        "monthly_revenue": total_revenue,
                        "avg_per_course": revenue_per_student,
                        "growth_rate": Decimal(str(round(random.uniform(-10, 25), 2))),
                        "predicted_revenue": Decimal(str(round(float(total_revenue) * random.uniform(1.0, 1.3), 2))),
                        "confidence_score": Decimal(str(round(random.uniform(70, 95), 2))),
                    },
                )
                revenue_count += 1

        self.stdout.write(f"Created {revenue_count} revenue analytics records.")

    def _print_credentials(self):
        """Print login credentials for testing."""
        self.stdout.write("\n" + "-" * 60)
        self.stdout.write(self.style.SUCCESS("TEST CREDENTIALS"))
        self.stdout.write("-" * 60)
        self.stdout.write(f"Password for all accounts: {DEFAULT_PASSWORD}\n")
        
        self.stdout.write(self.style.WARNING("Superuser:"))
        self.stdout.write("  admin@lms.local\n")
        
        for config in TENANT_CONFIGS:
            self.stdout.write(self.style.WARNING(f"{config['name']} ({config['domain']}):"))
            self.stdout.write(f"  Admin: admin@{config['slug']}.local")
            self.stdout.write(f"  Instructor: john.smith@{config['slug']}.local")
            self.stdout.write(f"  Learner: alice.williams@{config['slug']}.local\n")
