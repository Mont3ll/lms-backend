# Generated data migration for seeding instructor reports

from django.db import migrations


def seed_instructor_reports(apps, schema_editor):
    """
    Seed the default instructor reports into the database.
    These are system-wide reports (tenant=None) that are available to all instructors.
    """
    Report = apps.get_model('analytics', 'Report')
    
    instructor_reports = [
        {
            'name': 'Student Progress',
            'slug': 'student-progress',
            'description': 'Track student progress across your courses. View detailed metrics on module completion, time spent, and learning milestones.',
            'config': {
                'report_type': 'progress',
                'metrics': ['completion_rate', 'time_spent', 'modules_completed'],
                'grouping': ['course', 'student'],
                'access_level': 'INSTRUCTOR',
            },
        },
        {
            'name': 'Course Completion Rates',
            'slug': 'course-completion',
            'description': 'View completion rates for your courses. Analyze trends in student completion and identify areas for improvement.',
            'config': {
                'report_type': 'completion',
                'metrics': ['completion_rate', 'dropout_rate', 'average_time_to_complete'],
                'grouping': ['course', 'time_period'],
                'access_level': 'INSTRUCTOR',
            },
        },
        {
            'name': 'Assessment Results',
            'slug': 'assessment-results',
            'description': 'Analyze assessment performance and results. Review scores, pass rates, and question-level analytics.',
            'config': {
                'report_type': 'assessment',
                'metrics': ['average_score', 'pass_rate', 'attempt_count', 'question_analysis'],
                'grouping': ['assessment', 'course', 'student'],
                'access_level': 'INSTRUCTOR',
            },
        },
        {
            'name': 'Engagement Metrics',
            'slug': 'engagement-metrics',
            'description': 'Monitor student engagement levels. Track login frequency, content interactions, and participation trends.',
            'config': {
                'report_type': 'engagement',
                'metrics': ['login_frequency', 'content_views', 'discussion_participation', 'time_on_platform'],
                'grouping': ['course', 'student', 'time_period'],
                'access_level': 'INSTRUCTOR',
            },
        },
        {
            'name': 'Course Analytics',
            'slug': 'course-analytics',
            'description': 'Comprehensive analytics for your courses. View enrollment trends, revenue, ratings, and overall performance.',
            'config': {
                'report_type': 'course_overview',
                'metrics': ['enrollment_count', 'revenue', 'average_rating', 'completion_rate'],
                'grouping': ['course', 'time_period'],
                'access_level': 'INSTRUCTOR',
            },
        },
        {
            'name': 'Student Performance',
            'slug': 'student-performance',
            'description': 'Detailed performance analysis for individual students. Compare performance across assessments and track improvement over time.',
            'config': {
                'report_type': 'student_performance',
                'metrics': ['assessment_scores', 'progress_rate', 'improvement_trend'],
                'grouping': ['student', 'assessment', 'time_period'],
                'access_level': 'INSTRUCTOR',
            },
        },
    ]
    
    for report_data in instructor_reports:
        Report.objects.get_or_create(
            slug=report_data['slug'],
            defaults={
                'name': report_data['name'],
                'description': report_data['description'],
                'config': report_data['config'],
                'tenant': None,  # System-wide reports
            }
        )


def remove_instructor_reports(apps, schema_editor):
    """
    Remove the seeded instructor reports.
    """
    Report = apps.get_model('analytics', 'Report')
    instructor_slugs = [
        'student-progress',
        'course-completion',
        'assessment-results',
        'engagement-metrics',
        'course-analytics',
        'student-performance',
    ]
    Report.objects.filter(slug__in=instructor_slugs, tenant__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('analytics', '0003_instructoranalytics_active_enrollments_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_instructor_reports, remove_instructor_reports),
    ]
