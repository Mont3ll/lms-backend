import random
import uuid

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.assessments.models import Assessment, Question
from apps.core.models import Tenant, TenantDomain
from apps.courses.models import ContentItem, Course, Module
from apps.enrollments.models import Enrollment, LearnerProgress

User = get_user_model()

# Constants for Demo Data
NUM_TENANTS = 2
NUM_USERS_PER_TENANT = 10
NUM_COURSES_PER_TENANT = 5
NUM_MODULES_PER_COURSE = 3
NUM_ITEMS_PER_MODULE = 4
DEFAULT_PASSWORD = "password123"


class Command(BaseCommand):
    help = "Seeds the database with demo data for tenants, users, courses, etc."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting database seeding..."))

        if User.objects.filter(is_superuser=True).exists():
            self.stdout.write(
                self.style.WARNING(
                    "Superuser already exists. Ensure password is known."
                )
            )
        else:
            self.stdout.write(
                "Creating superuser 'admin@lms.demo' with password 'password123'..."
            )
            User.objects.create_superuser(
                "admin@lms.demo",
                DEFAULT_PASSWORD,
                first_name="Admin",
                last_name="Super",
            )

        tenants = self._create_tenants()
        for tenant in tenants:
            self.stdout.write(f"--- Seeding Tenant: {tenant.name} ---")
            users = self._create_users(tenant)
            instructor = users[0]  # Designate first user as instructor for simplicity
            instructor.role = User.Role.INSTRUCTOR
            instructor.save()
            learners = users[1:]

            courses = self._create_courses(tenant, instructor)
            for course in courses:
                self._create_modules_and_content(course)
                assessment = self._create_assessment(
                    course
                )  # Add one assessment per course
                self._enroll_users(learners, course)
                # Simulate some progress
                if learners:
                    self._simulate_progress(
                        learners[0], course
                    )  # Simulate for first learner

        self.stdout.write(
            self.style.SUCCESS("Database seeding completed successfully!")
        )

    def _create_tenants(self):
        tenants = []
        for i in range(1, NUM_TENANTS + 1):
            name = f"Demo Tenant {i}"
            slug = f"tenant-{i}"
            tenant, created = Tenant.objects.get_or_create(
                slug=slug, defaults={"name": name}
            )
            if created:
                domain_name = f"tenant{i}.lms.demo"  # Use .demo TLD for safety
                TenantDomain.objects.create(
                    tenant=tenant, domain=domain_name, is_primary=True
                )
                self.stdout.write(f"Created Tenant: {name} ({domain_name})")
            tenants.append(tenant)
        return tenants

    def _create_users(self, tenant):
        users = []
        for i in range(NUM_USERS_PER_TENANT):
            role = User.Role.LEARNER  # Default to learner
            status = User.Status.ACTIVE
            first_name = f"User{i:02d}"
            last_name = tenant.slug.replace("-", "").capitalize()
            email = f"{first_name.lower()}.{last_name.lower()}@lms.demo"

            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "first_name": first_name,
                    "last_name": last_name,
                    "role": role,
                    "status": status,
                    "tenant": tenant,
                },
            )
            if created:
                user.set_password(DEFAULT_PASSWORD)
                user.save()
                self.stdout.write(f"  Created User: {email}")
            users.append(user)
        return users

    def _create_courses(self, tenant, instructor):
        courses = []
        course_titles = [
            "Introduction to Python Programming",
            "Web Development Fundamentals",
            "Data Science Basics",
            "Project Management Essentials",
            "Digital Marketing Strategies",
        ]
        for i in range(NUM_COURSES_PER_TENANT):
            title = f"{random.choice(course_titles)} ({tenant.name})"
            status = random.choice([Course.Status.DRAFT, Course.Status.PUBLISHED])
            course, created = Course.objects.get_or_create(
                # Ensure uniqueness if slug needs to be unique per tenant only
                # slug=f"{slugify(title)}-{tenant.id}",
                tenant=tenant,
                # Use generate_unique_slug logic or simplify for seeding
                defaults={
                    "title": title,
                    "instructor": instructor,
                    "status": status,
                    "description": f"Description for {title}.",
                },
            )
            # Manually create slug if get_or_create doesn't trigger save method's slug generation
            if created and not course.slug:
                from apps.common.utils import generate_unique_slug

                course.slug = generate_unique_slug(course, source_field="title")
                course.save()

            if created:
                self.stdout.write(f"  Created Course: {title} (Status: {status})")
            courses.append(course)
        return courses

    def _create_modules_and_content(self, course):
        for i in range(1, NUM_MODULES_PER_COURSE + 1):
            module, m_created = Module.objects.get_or_create(
                course=course,
                order=i,
                defaults={
                    "title": f"Module {i}: {random.choice(['Setup', 'Core Concepts', 'Advanced Topics', 'Examples'])}"
                },
            )
            if m_created:
                self.stdout.write(f"    Created Module: {module.title}")

            # Create content items
            for j in range(1, NUM_ITEMS_PER_MODULE + 1):
                content_type = random.choice(
                    [
                        ContentItem.ContentType.TEXT,
                        ContentItem.ContentType.URL,
                        ContentItem.ContentType.VIDEO,  # Assume VIDEO uses external_url for demo
                    ]
                )
                defaults = {
                    "title": f"Lesson {i}.{j}",
                    "content_type": content_type,
                    "is_published": course.status == Course.Status.PUBLISHED,
                }
                if content_type == ContentItem.ContentType.TEXT:
                    defaults["text_content"] = (
                        f"This is the text content for Lesson {i}.{j}. \n\nLorem ipsum dolor sit amet..."
                    )
                elif (
                    content_type == ContentItem.ContentType.URL
                    or content_type == ContentItem.ContentType.VIDEO
                ):
                    defaults["external_url"] = (
                        f"https://example.com/resource/{uuid.uuid4()}"  # Placeholder URL
                    )

                item, i_created = ContentItem.objects.get_or_create(
                    module=module, order=j, defaults=defaults
                )
                if i_created:
                    self.stdout.write(
                        f"      Created ContentItem: {item.title} ({item.get_content_type_display()})"
                    )

    def _create_assessment(self, course):
        assessment, a_created = Assessment.objects.get_or_create(
            course=course,
            assessment_type=Assessment.AssessmentType.QUIZ,
            defaults={
                "title": f"End of Course Quiz: {course.title}",
                "is_published": course.status == Course.Status.PUBLISHED,
                "grading_type": Assessment.GradingType.AUTO,
                "pass_mark_percentage": 70,
            },
        )
        if a_created:
            self.stdout.write(f"    Created Assessment: {assessment.title}")
            # Add some questions
            for i in range(1, 6):  # 5 Questions
                q_created = Question.objects.create(
                    assessment=assessment,
                    order=i,
                    question_type=Question.QuestionType.MULTIPLE_CHOICE,
                    question_text=f"Question {i}: What is the capital of imaginary country {i}?",
                    points=2,
                    type_specific_data={
                        "options": [
                            {
                                "id": str(uuid.uuid4()),
                                "text": "Option A",
                                "is_correct": i % 3 == 0,
                            },
                            {
                                "id": str(uuid.uuid4()),
                                "text": "Option B",
                                "is_correct": i % 3 == 1,
                            },
                            {
                                "id": str(uuid.uuid4()),
                                "text": "Option C",
                                "is_correct": i % 3 == 2,
                            },
                        ],
                        "allow_multiple": False,
                    },
                )
                if q_created:
                    self.stdout.write(
                        f"      Created Question {i} for Assessment {assessment.title}"
                    )
        return assessment

    def _enroll_users(self, learners, course):
        enrollments_to_create = []
        for learner in learners:
            # Check if already exists before adding to list (avoid IntegrityError with bulk_create)
            if not Enrollment.objects.filter(user=learner, course=course).exists():
                enrollments_to_create.append(
                    Enrollment(
                        user=learner, course=course, status=Enrollment.Status.ACTIVE
                    )
                )
        if enrollments_to_create:
            Enrollment.objects.bulk_create(enrollments_to_create)
            self.stdout.write(
                f"  Enrolled {len(enrollments_to_create)} learners in {course.title}"
            )

    def _simulate_progress(self, learner, course):
        enrollment = Enrollment.objects.filter(user=learner, course=course).first()
        if not enrollment:
            return

        content_items = list(
            ContentItem.objects.filter(
                module__course=course, is_published=True
            ).order_by("module__order", "order")
        )
        items_to_complete = int(len(content_items) * 0.6)  # Complete ~60%

        for i, item in enumerate(content_items):
            if i < items_to_complete:
                prog, created = LearnerProgress.objects.get_or_create(
                    enrollment=enrollment, content_item=item
                )
                if prog.status != LearnerProgress.Status.COMPLETED:
                    prog.mark_as_completed()  # Simulate completion
                    if i == 0:
                        self.stdout.write(
                            f"    Simulated progress for {learner.email} in {course.title}"
                        )
