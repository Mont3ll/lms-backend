from django.core.management.base import BaseCommand
from apps.analytics.models import Report


class Command(BaseCommand):
    help = 'Create initial report definitions for the analytics system'

    def handle(self, *args, **options):
        # Define the initial reports that instructors need
        reports_to_create = [
            {
                'name': 'Student Progress Report',
                'slug': 'student-progress',
                'description': 'Track student progress and engagement across your courses',
                'config': {
                    'data_source': 'enrollments',
                    'grouping': 'course',
                    'metrics': ['progress_percentage', 'completion_status', 'last_activity']
                }
            },
            {
                'name': 'Course Completion Report',
                'slug': 'course-completion',
                'description': 'Analysis of course completion rates and student performance',
                'config': {
                    'data_source': 'enrollments',
                    'grouping': 'course',
                    'metrics': ['completion_rate', 'average_progress', 'enrollment_count']
                }
            },
            {
                'name': 'Assessment Results Report',
                'slug': 'assessment-results',
                'description': 'Student performance on assessments and quizzes',
                'config': {
                    'data_source': 'assessment_attempts',
                    'grouping': 'assessment',
                    'metrics': ['average_score', 'pass_rate', 'attempt_count']
                }
            },
            {
                'name': 'User Activity Report',
                'slug': 'user-activity-summary',
                'description': 'Summary of user login and activity patterns',
                'config': {
                    'data_source': 'events',
                    'grouping': 'user',
                    'metrics': ['login_count', 'last_activity', 'content_views']
                }
            }
        ]

        created_count = 0
        for report_data in reports_to_create:
            report, created = Report.objects.get_or_create(
                slug=report_data['slug'],
                defaults={
                    'name': report_data['name'],
                    'description': report_data['description'],
                    'config': report_data['config'],
                    'tenant': None  # System-wide reports
                }
            )
            
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f'Created report: {report.name} ({report.slug})')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'Report already exists: {report.name} ({report.slug})')
                )

        self.stdout.write(
            self.style.SUCCESS(f'\nCompleted! Created {created_count} new reports.')
        )