from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from datetime import timedelta, date
import random
import uuid

from apps.analytics.models import *
from apps.users.models import User
from apps.courses.models import Course
from apps.enrollments.models import Enrollment
from apps.core.models import Tenant
from apps.assessments.models import Assessment


class Command(BaseCommand):
    help = 'Generate sample analytics data for testing'

    def handle(self, *args, **options):
        with transaction.atomic():
            # Get or create a tenant
            tenant, _ = Tenant.objects.get_or_create(
                name='Demo Tenant',
                defaults={'slug': 'demo-tenant'}
            )
            
            # Clear existing analytics data
            self.stdout.write('Clearing existing analytics data...')
            StudentPerformance.objects.all().delete()
            EngagementMetrics.objects.all().delete()
            CourseAnalytics.objects.all().delete()
            InstructorAnalytics.objects.all().delete()
            RevenueAnalytics.objects.all().delete()
            ActivityFeed.objects.all().delete()
            StudySession.objects.all().delete()
            DiscussionInteraction.objects.all().delete()
            
            # Get existing users and courses
            users = User.objects.filter(role=User.Role.LEARNER)[:10]
            courses = Course.objects.all()[:5]
            instructors = User.objects.filter(role=User.Role.INSTRUCTOR)[:3]
            
            if not users.exists():
                self.stdout.write(self.style.ERROR('No learner users found. Please create some users first.'))
                return
                
            if not courses.exists():
                self.stdout.write(self.style.ERROR('No courses found. Please create some courses first.'))
                return
            
            count = 0
            
            # Generate analytics for each user-course combination
            for user in users:
                for course in courses:
                    # Only create analytics if there's an enrollment
                    if Enrollment.objects.filter(user=user, course=course).exists():
                        # Generate study sessions
                        for i in range(random.randint(5, 15)):
                            session_start = timezone.now() - timedelta(days=random.randint(1, 30))
                            session_duration = timedelta(minutes=random.randint(15, 120))
                            
                            StudySession.objects.create(
                                tenant=tenant,
                                user=user,
                                course=course,
                                session_id=str(uuid.uuid4()),
                                started_at=session_start,
                                ended_at=session_start + session_duration,
                                duration=session_duration,
                                pages_visited=random.randint(5, 20),
                                videos_watched=random.randint(1, 5),
                                quizzes_attempted=random.randint(0, 3),
                                downloads=random.randint(0, 5),
                                device_type=random.choice(['desktop', 'mobile', 'tablet']),
                                browser=random.choice(['Chrome', 'Firefox', 'Safari', 'Edge']),
                                os=random.choice(['Windows', 'macOS', 'Linux', 'iOS', 'Android']),
                                country=random.choice(['US', 'UK', 'Canada', 'Australia', 'Germany']),
                                region=random.choice(['North America', 'Europe', 'Asia', 'Oceania']),
                                engagement_score=random.randint(60, 100),
                                focus_time=timedelta(minutes=random.randint(10, 90))
                            )
                        
                        # Generate discussion interactions
                        for i in range(random.randint(2, 8)):
                            DiscussionInteraction.objects.create(
                                tenant=tenant,
                                user=user,
                                course=course,
                                interaction_type=random.choice(['post', 'reply', 'like', 'view']),
                                discussion_id=f"discussion_{random.randint(1, 10)}",
                                post_id=f"post_{random.randint(1, 100)}",
                                content_length=random.randint(50, 500),
                                likes_received=random.randint(0, 10),
                                replies_received=random.randint(0, 5),
                                quality_score=random.randint(60, 100),
                                helpfulness_rating=random.randint(3, 5)
                            )
                        
                        # Generate activity feed entries
                        activity_types = [
                            'course_enrollment', 'lesson_completion', 'assessment_submission',
                            'discussion_post', 'assignment_submission'
                        ]
                        for activity_type in activity_types:
                            if random.random() > 0.3:  # 70% chance to create each activity type
                                ActivityFeed.objects.create(
                                    tenant=tenant,
                                    user=user,
                                    course=course,
                                    activity_type=activity_type,
                                    title=f"{activity_type.replace('_', ' ').title()}",
                                    description=f"User {user.email} performed {activity_type.replace('_', ' ')} in {course.title}",
                                    metadata={'score': random.randint(70, 100)} if 'assessment' in activity_type else {},
                                    importance=random.choice(['low', 'medium', 'high'])
                                )
                        
                        # Create student performance
                        StudentPerformance.objects.create(
                            tenant=tenant,
                            student=user,
                            course=course,
                            assessment=None,
                            score=random.uniform(70, 100),
                            completion_rate=random.uniform(60, 100),
                            time_spent=timedelta(hours=random.randint(10, 100)),
                            completion_time=timedelta(hours=random.randint(1, 10)),
                            attempts=random.randint(1, 3),
                            last_activity=timezone.now() - timedelta(days=random.randint(1, 30)),
                            risk_score=random.uniform(0, 100),
                            risk_factors=["low_engagement", "missed_deadlines"] if random.random() > 0.7 else []
                        )
                        
                        # Create engagement metrics
                        EngagementMetrics.objects.create(
                            tenant=tenant,
                            student=user,
                            course=course,
                            date=timezone.now().date(),
                            active_users=random.randint(50, 200),
                            session_duration=timedelta(minutes=random.randint(30, 180)),
                            page_views=random.randint(10, 100),
                            interactions=random.randint(20, 200),
                            video_watch_time=timedelta(minutes=random.randint(15, 120)),
                            quiz_attempts=random.randint(1, 10),
                            forum_posts=random.randint(0, 10),
                            device_type='desktop',
                            geographic_region='North America'
                        )
                        
                        count += 1
            
            # Generate revenue analytics for instructors
            for instructor in instructors:
                instructor_courses = Course.objects.filter(instructor=instructor)
                if instructor_courses.exists():
                    # Generate monthly revenue data for last 12 months
                    for i in range(12):
                        period_start = (date.today() - timedelta(days=30 * i)).replace(day=1)
                        period_end = period_start + timedelta(days=30)
                        
                        total_revenue = random.randint(1000, 5000)
                        enrolled_students = random.randint(10, 50)
                        
                        RevenueAnalytics.objects.create(
                            tenant=tenant,
                            instructor=instructor,
                            course=random.choice(instructor_courses),
                            period_start=period_start,
                            period_end=period_end,
                            total_revenue=total_revenue,
                            enrolled_students=enrolled_students,
                            revenue_per_student=total_revenue / enrolled_students,
                            monthly_revenue=total_revenue,
                            avg_per_course=total_revenue / instructor_courses.count(),
                            growth_rate=random.randint(-10, 25),
                            predicted_revenue=total_revenue * (1 + random.randint(-5, 15) / 100),
                            confidence_score=random.randint(70, 95)
                        )
                        
                    # Generate instructor analytics
                    InstructorAnalytics.objects.create(
                        tenant=tenant,
                        instructor_id=instructor.id,
                        total_courses=instructor_courses.count(),
                        published_courses=instructor_courses.filter(status=Course.Status.PUBLISHED).count(),
                        draft_courses=instructor_courses.filter(status=Course.Status.DRAFT).count(),
                        total_students=random.randint(50, 200),
                        active_students=random.randint(30, 150),
                        new_students=random.randint(5, 25),
                        avg_course_rating=random.randint(40, 50) / 10,
                        avg_completion_rate=random.randint(60, 90),
                        avg_engagement_rate=random.randint(70, 95),
                        total_revenue=random.randint(5000, 25000),
                        monthly_revenue=random.randint(1000, 5000),
                        avg_revenue_per_student=random.randint(50, 200),
                        student_growth_rate=random.randint(-5, 20),
                        revenue_growth_rate=random.randint(-10, 30),
                        pending_grading=random.randint(0, 15),
                        total_enrollments=random.randint(100, 500),
                        active_enrollments=random.randint(50, 250),
                        modules_created=random.randint(10, 50),
                        content_items_created=random.randint(50, 200),
                        published_this_month=random.randint(1, 10),
                        date=date.today()
                    )
            
            # Create course analytics for each course
            for course in courses:
                CourseAnalytics.objects.get_or_create(
                    tenant=tenant,
                    course_id=course.id,
                    date=timezone.now().date(),
                    defaults={
                        'instructor_id': course.instructor.id if course.instructor else None,
                        'total_enrollments': random.randint(50, 200),
                        'active_enrollments': random.randint(30, 150),
                        'completed_enrollments': random.randint(10, 50),
                        'avg_completion_rate': random.uniform(60, 90),
                        'avg_engagement_score': random.uniform(70, 95),
                        'avg_rating': random.uniform(4.0, 5.0),
                        'total_reviews': random.randint(20, 100),
                        'total_revenue': random.uniform(1000, 10000),
                    }
                )
            
            self.stdout.write(
                self.style.SUCCESS(f'Successfully generated sample analytics data for {count} user-course combinations')
            )
