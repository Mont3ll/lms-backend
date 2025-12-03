from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from apps.learning_paths.models import LearningPath, LearningPathStep
from apps.courses.models import Course, Module
from apps.core.models import Tenant


class Command(BaseCommand):
    help = 'Create sample learning paths for demo purposes'

    def handle(self, *args, **options):
        # Get a tenant that has published courses
        try:
            tenant = None
            for t in Tenant.objects.all():
                if Course.objects.filter(tenant=t, status=Course.Status.PUBLISHED).exists():
                    tenant = t
                    break
            
            if not tenant:
                self.stdout.write(
                    self.style.ERROR('No tenants found with published courses. Please create some courses first.')
                )
                return
                
            self.stdout.write(f'Using tenant: {tenant.name}')
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error finding tenant: {e}')
            )
            return

        # Create sample learning paths
        learning_paths_data = [
            {
                'title': 'Python Programming Journey',
                'slug': f'python-programming-journey-{tenant.name.lower().replace(" ", "-")}',
                'description': 'Master Python programming from basics to advanced concepts through a carefully curated sequence of courses.',
                'status': LearningPath.Status.PUBLISHED,
            },
            {
                'title': 'Web Development Fundamentals',
                'slug': f'web-development-fundamentals-{tenant.name.lower().replace(" ", "-")}',
                'description': 'Learn the essential skills for modern web development including HTML, CSS, JavaScript, and React.',
                'status': LearningPath.Status.PUBLISHED,
            },
            {
                'title': 'Data Science Pathway',
                'slug': f'data-science-pathway-{tenant.name.lower().replace(" ", "-")}',
                'description': 'Comprehensive path to becoming a data scientist, covering statistics, Python, and machine learning.',
                'status': LearningPath.Status.PUBLISHED,
            }
        ]

        for path_data in learning_paths_data:
            # Create or get the learning path
            learning_path, created = LearningPath.objects.get_or_create(
                slug=path_data['slug'],
                defaults={**path_data, 'tenant': tenant}
            )
            
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'Created learning path: {learning_path.title}')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'Learning path already exists: {learning_path.title}')
                )

            # Add courses to the learning path as steps
            self.add_steps_to_learning_path(learning_path)

    def add_steps_to_learning_path(self, learning_path):
        """Add course steps to the learning path"""
        
        # Get available courses for this tenant
        courses = Course.objects.filter(
            tenant=learning_path.tenant,
            status=Course.Status.PUBLISHED
        ).order_by('title')[:3]  # Get first 3 courses
        
        if not courses.exists():
            self.stdout.write(
                self.style.WARNING(f'No published courses found for tenant {learning_path.tenant.name}')
            )
            return

        # Clear existing steps
        learning_path.steps.all().delete()

        # Add courses as steps
        course_content_type = ContentType.objects.get_for_model(Course)
        
        for idx, course in enumerate(courses, 1):
            step = LearningPathStep.objects.create(
                learning_path=learning_path,
                order=idx,
                content_type=course_content_type,
                object_id=course.id,
                is_required=True
            )
            self.stdout.write(
                self.style.SUCCESS(f'  Added step {idx}: {course.title}')
            )

        self.stdout.write(
            self.style.SUCCESS(f'Added {courses.count()} steps to {learning_path.title}')
        )
