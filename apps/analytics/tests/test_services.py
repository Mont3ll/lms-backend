"""
Tests for analytics app services.
"""
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.utils import timezone

from apps.core.models import Tenant
from apps.users.models import User
from apps.courses.models import Course
from apps.enrollments.models import Enrollment
from apps.assessments.models import Assessment, AssessmentAttempt

from apps.analytics.models import (
    Event, Report, StudentEngagementMetric, CourseAnalytics,
    InstructorAnalytics, PredictiveAnalytics, AIInsights, RealTimeMetrics,
    StudySession
)
from apps.analytics.services import (
    AnalyticsService, ReportGeneratorService, ReportGenerationError,
    DataProcessorService, ExportService, VisualizationService
)


class AnalyticsServiceTestCase(TestCase):
    """Tests for AnalyticsService."""

    def setUp(self):
        """Set up test data."""
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant"
        )
        self.instructor = User.objects.create_user(
            email="instructor@test.com",
            password="testpass123",
            first_name="Test",
            last_name="Instructor",
            role="instructor",
            tenant=self.tenant
        )
        self.learner = User.objects.create_user(
            email="learner@test.com",
            password="testpass123",
            first_name="Test",
            last_name="Learner",
            role="learner",
            tenant=self.tenant
        )
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            slug="test-course",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
            price=Decimal("99.99")
        )
        self.enrollment = Enrollment.objects.create(
            user=self.learner,
            course=self.course,
            status=Enrollment.Status.ACTIVE
        )

    def test_track_event_valid_event_type(self):
        """Test tracking a valid event type."""
        AnalyticsService.track_event(
            user=self.learner,
            event_type="USER_LOGIN",
            context_data={"source": "web"},
            tenant=self.tenant
        )

        event = Event.objects.first()
        self.assertIsNotNone(event)
        self.assertEqual(event.user, self.learner)
        self.assertEqual(event.event_type, "USER_LOGIN")
        self.assertEqual(event.context_data, {"source": "web"})
        self.assertEqual(event.tenant, self.tenant)

    def test_track_event_invalid_event_type(self):
        """Test tracking an invalid event type does not create an event."""
        initial_count = Event.objects.count()
        
        AnalyticsService.track_event(
            user=self.learner,
            event_type="INVALID_EVENT_TYPE",
            context_data={},
            tenant=self.tenant
        )

        self.assertEqual(Event.objects.count(), initial_count)

    def test_track_event_with_request_extracts_metadata(self):
        """Test that event tracking extracts metadata from request."""
        mock_request = MagicMock()
        mock_request.META = {
            "HTTP_X_FORWARDED_FOR": "192.168.1.100, 10.0.0.1",
            "HTTP_USER_AGENT": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0)",
            "REMOTE_ADDR": "127.0.0.1"
        }
        mock_request.session = MagicMock()
        mock_request.session.session_key = "test-session-key"

        AnalyticsService.track_event(
            user=self.learner,
            event_type="COURSE_VIEW",
            context_data={"course_id": str(self.course.id)},
            tenant=self.tenant,
            request=mock_request
        )

        event = Event.objects.first()
        self.assertEqual(event.ip_address, "192.168.1.100")
        self.assertEqual(event.session_id, "test-session-key")
        self.assertEqual(event.device_type, "mobile")

    def test_track_event_browser_detection(self):
        """Test browser detection from user agent."""
        test_cases = [
            ("Mozilla/5.0 Chrome/91.0", "Chrome"),
            ("Mozilla/5.0 Firefox/89.0", "Firefox"),
            ("Mozilla/5.0 Safari/605.1", "Safari"),
            ("Mozilla/5.0 Edge/91.0", "Edge"),  # Service checks for 'edge' in lowercase
            ("Unknown Browser", "Other"),
        ]

        for user_agent, expected_browser in test_cases:
            Event.objects.all().delete()
            mock_request = MagicMock()
            mock_request.META = {
                "HTTP_USER_AGENT": user_agent,
                "REMOTE_ADDR": "127.0.0.1"
            }
            mock_request.session = None

            AnalyticsService.track_event(
                user=self.learner,
                event_type="PAGE_VIEW",
                tenant=self.tenant,
                request=mock_request
            )

            event = Event.objects.first()
            self.assertEqual(event.browser, expected_browser, f"Failed for user agent: {user_agent}")

    def test_track_event_device_type_detection(self):
        """Test device type detection from user agent."""
        test_cases = [
            ("Mozilla/5.0 (iPhone; CPU iPhone OS)", "mobile"),
            ("Mozilla/5.0 (Android)", "mobile"),
            ("Mozilla/5.0 (iPad)", "tablet"),
            ("Mozilla/5.0 (Windows NT 10.0)", "desktop"),
        ]

        for user_agent, expected_device in test_cases:
            Event.objects.all().delete()
            mock_request = MagicMock()
            mock_request.META = {
                "HTTP_USER_AGENT": user_agent,
                "REMOTE_ADDR": "127.0.0.1"
            }
            mock_request.session = None

            AnalyticsService.track_event(
                user=self.learner,
                event_type="PAGE_VIEW",
                tenant=self.tenant,
                request=mock_request
            )

            event = Event.objects.first()
            self.assertEqual(event.device_type, expected_device, f"Failed for user agent: {user_agent}")

    def test_track_event_handles_non_serializable_context_data(self):
        """Test that non-serializable context data is handled gracefully."""
        # Create an object that cannot be JSON serialized
        non_serializable = {"func": lambda x: x}
        
        AnalyticsService.track_event(
            user=self.learner,
            event_type="CONTENT_VIEW",
            context_data=non_serializable,
            tenant=self.tenant
        )

        event = Event.objects.first()
        self.assertIsNotNone(event)
        self.assertEqual(event.context_data, {"error": "Invalid context data provided"})

    def test_track_event_without_user(self):
        """Test tracking an event without a user (anonymous event)."""
        AnalyticsService.track_event(
            user=None,
            event_type="PAGE_VIEW",
            context_data={"page": "/home"},
            tenant=self.tenant
        )

        event = Event.objects.first()
        self.assertIsNotNone(event)
        self.assertIsNone(event.user)

    def test_calculate_active_time_no_events(self):
        """Test calculating active time with no events returns 0."""
        events = Event.objects.none()
        result = AnalyticsService._calculate_active_time(events)
        self.assertEqual(result, 0)

    def test_calculate_active_time_multiple_sessions(self):
        """Test calculating active time from multiple sessions."""
        now = timezone.now()
        
        # Create events in two different sessions
        # Note: created_at is auto_now_add, so we need to update after creation
        e1 = Event.objects.create(
            user=self.learner,
            event_type="PAGE_VIEW",
            tenant=self.tenant,
            session_id="session1"
        )
        Event.objects.filter(pk=e1.pk).update(created_at=now - timedelta(hours=2))
        
        e2 = Event.objects.create(
            user=self.learner,
            event_type="CONTENT_VIEW",
            tenant=self.tenant,
            session_id="session1"
        )
        Event.objects.filter(pk=e2.pk).update(created_at=now - timedelta(hours=1, minutes=30))
        
        e3 = Event.objects.create(
            user=self.learner,
            event_type="PAGE_VIEW",
            tenant=self.tenant,
            session_id="session2"
        )
        Event.objects.filter(pk=e3.pk).update(created_at=now - timedelta(minutes=30))
        
        e4 = Event.objects.create(
            user=self.learner,
            event_type="CONTENT_VIEW",
            tenant=self.tenant,
            session_id="session2"
        )
        Event.objects.filter(pk=e4.pk).update(created_at=now)

        events = Event.objects.filter(user=self.learner)
        result = AnalyticsService._calculate_active_time(events)
        # Should be approximately 30 minutes per session = 60 minutes total
        self.assertGreater(result, 0)

    def test_calculate_avg_session_duration_from_study_sessions(self):
        """Test calculating average session duration from StudySession model."""
        today = timezone.now().date()
        
        # Create study sessions with durations
        StudySession.objects.create(
            tenant=self.tenant,
            user=self.learner,
            course=self.course,
            session_id="session1",
            started_at=timezone.now() - timedelta(hours=1),
            duration=timedelta(minutes=30)
        )
        StudySession.objects.create(
            tenant=self.tenant,
            user=self.learner,
            course=self.course,
            session_id="session2",
            started_at=timezone.now() - timedelta(hours=2),
            duration=timedelta(minutes=60)
        )

        result = AnalyticsService._calculate_avg_session_duration(self.learner, today)
        # Average of 30 and 60 minutes = 45 minutes
        self.assertEqual(result, 45)

    def test_calculate_risk_score_low_activity(self):
        """Test that low activity increases risk score."""
        today = timezone.now().date()
        
        # Create only a few events
        Event.objects.create(
            user=self.learner,
            event_type="COURSE_VIEW",
            tenant=self.tenant,
            context_data={"course_id": str(self.course.id)},
            created_at=timezone.now() - timedelta(days=2)
        )

        risk_score = AnalyticsService._calculate_risk_score(self.learner, self.course, today)
        # Should have risk factors for low activity, no quiz attempts, and infrequent login
        self.assertGreater(risk_score, 0)
        self.assertLessEqual(risk_score, 100)

    def test_calculate_risk_score_active_student(self):
        """Test that active students have lower risk scores."""
        today = timezone.now().date()
        
        # Create many recent events
        for i in range(10):
            Event.objects.create(
                user=self.learner,
                event_type="CONTENT_VIEW",
                tenant=self.tenant,
                context_data={"course_id": str(self.course.id)},
                created_at=timezone.now() - timedelta(days=i % 7)
            )
        
        # Add quiz attempts
        for i in range(3):
            Event.objects.create(
                user=self.learner,
                event_type="QUIZ_ATTEMPT",
                tenant=self.tenant,
                context_data={"course_id": str(self.course.id)},
                created_at=timezone.now() - timedelta(days=i)
            )
        
        # Add logins
        for i in range(5):
            Event.objects.create(
                user=self.learner,
                event_type="USER_LOGIN",
                tenant=self.tenant,
                created_at=timezone.now() - timedelta(days=i)
            )

        risk_score = AnalyticsService._calculate_risk_score(self.learner, self.course, today)
        self.assertEqual(risk_score, 0)  # Active student should have 0 risk


class ProcessStudentEngagementMetricsTestCase(TestCase):
    """Tests for processing student engagement metrics."""

    def setUp(self):
        """Set up test data."""
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant"
        )
        self.instructor = User.objects.create_user(
            email="instructor@test.com",
            password="testpass123",
            role="instructor",
            tenant=self.tenant
        )
        self.learner = User.objects.create_user(
            email="learner@test.com",
            password="testpass123",
            role="learner",
            tenant=self.tenant
        )
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            slug="test-course",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED
        )
        self.enrollment = Enrollment.objects.create(
            user=self.learner,
            course=self.course,
            status=Enrollment.Status.ACTIVE
        )

    def test_process_student_engagement_metrics_creates_records(self):
        """Test that processing creates engagement metric records."""
        yesterday = timezone.now().date() - timedelta(days=1)
        
        # Create events with explicit datetime that matches yesterday's date
        yesterday_datetime = timezone.make_aware(
            datetime.combine(yesterday, datetime.min.time().replace(hour=12))
        )
        
        # Create some events for the learner
        # Note: created_at is auto_now_add, so we need to update after creation
        for event_type in ["CONTENT_VIEW", "VIDEO_WATCH", "QUIZ_ATTEMPT"]:
            event = Event.objects.create(
                user=self.learner,
                event_type=event_type,
                tenant=self.tenant,
                context_data={"course_id": str(self.course.id)}
            )
            Event.objects.filter(pk=event.pk).update(created_at=yesterday_datetime)

        AnalyticsService.process_student_engagement_metrics(self.tenant, yesterday)

        metric = StudentEngagementMetric.objects.filter(
            user=self.learner,
            course_id=self.course.id,
            date=yesterday
        ).first()
        
        self.assertIsNotNone(metric)
        self.assertEqual(metric.content_views, 1)
        self.assertEqual(metric.video_watches, 1)
        self.assertEqual(metric.quiz_attempts, 1)

    def test_process_student_engagement_metrics_updates_existing(self):
        """Test that processing updates existing metric records."""
        yesterday = timezone.now().date() - timedelta(days=1)
        
        # Create initial metric
        metric = StudentEngagementMetric.objects.create(
            tenant=self.tenant,
            user=self.learner,
            course_id=self.course.id,
            date=yesterday,
            content_views=5
        )
        
        # Create events with explicit datetime that matches yesterday's date
        yesterday_datetime = timezone.make_aware(
            datetime.combine(yesterday, datetime.min.time().replace(hour=12))
        )
        
        # Create new event (created_at is auto_now_add, so update after creation)
        event = Event.objects.create(
            user=self.learner,
            event_type="CONTENT_VIEW",
            tenant=self.tenant,
            context_data={"course_id": str(self.course.id)}
        )
        Event.objects.filter(pk=event.pk).update(created_at=yesterday_datetime)

        AnalyticsService.process_student_engagement_metrics(self.tenant, yesterday)

        metric.refresh_from_db()
        self.assertEqual(metric.content_views, 1)  # Updated to actual count


class ProcessCourseAnalyticsTestCase(TestCase):
    """Tests for processing course analytics."""

    def setUp(self):
        """Set up test data."""
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant"
        )
        self.instructor = User.objects.create_user(
            email="instructor@test.com",
            password="testpass123",
            role="instructor",
            tenant=self.tenant
        )
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            slug="test-course",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
            price=Decimal("100.00")
        )

    def test_process_course_analytics_creates_records(self):
        """Test that processing creates course analytics records."""
        yesterday = timezone.now().date() - timedelta(days=1)
        
        # Create enrollments
        for i in range(5):
            user = User.objects.create_user(
                email=f"learner{i}@test.com",
                password="testpass123",
                role="learner",
                tenant=self.tenant
            )
            Enrollment.objects.create(
                user=user,
                course=self.course,
                status=Enrollment.Status.ACTIVE if i < 3 else Enrollment.Status.COMPLETED
            )

        AnalyticsService.process_course_analytics(self.tenant, yesterday)

        analytics = CourseAnalytics.objects.filter(
            course_id=self.course.id,
            date=yesterday
        ).first()
        
        self.assertIsNotNone(analytics)
        self.assertEqual(analytics.total_enrollments, 5)
        self.assertEqual(analytics.active_enrollments, 3)
        self.assertEqual(analytics.completed_enrollments, 2)
        self.assertEqual(analytics.avg_completion_rate, 40)  # 2/5 * 100


class ProcessInstructorAnalyticsTestCase(TestCase):
    """Tests for processing instructor analytics."""

    def setUp(self):
        """Set up test data."""
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant"
        )
        self.instructor = User.objects.create_user(
            email="instructor@test.com",
            password="testpass123",
            role="instructor",
            tenant=self.tenant
        )
        self.course1 = Course.objects.create(
            tenant=self.tenant,
            title="Course 1",
            slug="course-1",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED
        )
        self.course2 = Course.objects.create(
            tenant=self.tenant,
            title="Course 2",
            slug="course-2",
            instructor=self.instructor,
            status=Course.Status.DRAFT
        )

    def test_process_instructor_analytics_creates_records(self):
        """Test that processing creates instructor analytics records."""
        yesterday = timezone.now().date() - timedelta(days=1)
        
        # Create enrollments
        for i in range(3):
            user = User.objects.create_user(
                email=f"learner{i}@test.com",
                password="testpass123",
                role="learner",
                tenant=self.tenant
            )
            Enrollment.objects.create(
                user=user,
                course=self.course1,
                status=Enrollment.Status.ACTIVE
            )

        AnalyticsService.process_instructor_analytics(self.tenant, yesterday)

        analytics = InstructorAnalytics.objects.filter(
            instructor_id=self.instructor.id,
            date=yesterday
        ).first()
        
        self.assertIsNotNone(analytics)
        self.assertEqual(analytics.total_courses, 2)
        self.assertEqual(analytics.published_courses, 1)
        self.assertEqual(analytics.draft_courses, 1)
        self.assertEqual(analytics.total_students, 3)


class GenerateAIInsightsTestCase(TestCase):
    """Tests for AI insights generation."""

    def setUp(self):
        """Set up test data."""
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant"
        )
        self.instructor = User.objects.create_user(
            email="instructor@test.com",
            password="testpass123",
            role="instructor",
            tenant=self.tenant
        )

    def test_generate_ai_insights_no_analytics(self):
        """Test AI insights with no prior analytics data."""
        today = timezone.now().date()
        
        # Should not raise an error, just return early
        AnalyticsService.generate_ai_insights(self.tenant, self.instructor.id, today)
        
        # No insights should be created
        self.assertEqual(AIInsights.objects.count(), 0)

    def test_generate_ai_insights_with_analytics(self):
        """Test AI insights generation with analytics data."""
        today = timezone.now().date()
        yesterday = today - timedelta(days=1)
        
        # Create instructor analytics for two days
        InstructorAnalytics.objects.create(
            tenant=self.tenant,
            instructor_id=self.instructor.id,
            date=yesterday,
            total_students=100,
            active_students=80,
            avg_completion_rate=70,
            avg_engagement_rate=65,
            total_revenue=Decimal("5000.00")
        )
        InstructorAnalytics.objects.create(
            tenant=self.tenant,
            instructor_id=self.instructor.id,
            date=today,
            total_students=110,  # Growth
            active_students=85,
            avg_completion_rate=72,
            avg_engagement_rate=70,  # Improved engagement
            total_revenue=Decimal("5500.00")
        )

        AnalyticsService.generate_ai_insights(self.tenant, self.instructor.id, today)

        insights = AIInsights.objects.filter(
            instructor_id=self.instructor.id,
            date=today
        ).first()
        
        self.assertIsNotNone(insights)
        self.assertIsInstance(insights.key_insights, list)
        self.assertEqual(insights.confidence_score, 85.0)

    def test_generate_ai_insights_low_completion_rate(self):
        """Test AI insights flags low completion rate."""
        today = timezone.now().date()
        
        # Create analytics with low completion rate
        InstructorAnalytics.objects.create(
            tenant=self.tenant,
            instructor_id=self.instructor.id,
            date=today,
            total_students=100,
            avg_completion_rate=40,  # Low
            avg_engagement_rate=50,
            total_revenue=Decimal("1000.00")
        )

        AnalyticsService.generate_ai_insights(self.tenant, self.instructor.id, today)

        insights = AIInsights.objects.first()
        
        # Should have a warning about low completion rate
        warning_insights = [i for i in insights.key_insights if i.get('type') == 'warning']
        self.assertTrue(len(warning_insights) > 0)


class UpdateRealTimeMetricsTestCase(TestCase):
    """Tests for real-time metrics updates."""

    def setUp(self):
        """Set up test data."""
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant"
        )
        self.instructor = User.objects.create_user(
            email="instructor@test.com",
            password="testpass123",
            role="instructor",
            tenant=self.tenant
        )
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            slug="test-course",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED
        )

    def test_update_real_time_metrics_creates_record(self):
        """Test that updating real-time metrics creates a record."""
        AnalyticsService.update_real_time_metrics(self.tenant, self.instructor.id)

        metrics = RealTimeMetrics.objects.filter(
            instructor_id=self.instructor.id
        ).first()
        
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics.server_health, 100.0)

    def test_update_real_time_metrics_counts_active_users(self):
        """Test that real-time metrics counts active users correctly."""
        # Create recent events from different users
        for i in range(3):
            user = User.objects.create_user(
                email=f"learner{i}@test.com",
                password="testpass123",
                role="learner",
                tenant=self.tenant
            )
            Enrollment.objects.create(
                user=user,
                course=self.course,
                status=Enrollment.Status.ACTIVE
            )
            Event.objects.create(
                user=user,
                event_type="COURSE_VIEW",
                tenant=self.tenant,
                context_data={"course_id": str(self.course.id)},
                created_at=timezone.now() - timedelta(minutes=5)
            )

        AnalyticsService.update_real_time_metrics(self.tenant, self.instructor.id)

        metrics = RealTimeMetrics.objects.first()
        self.assertEqual(metrics.active_users, 3)


class ReportGeneratorServiceTestCase(TestCase):
    """Tests for ReportGeneratorService."""

    def setUp(self):
        """Set up test data."""
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant"
        )
        self.instructor = User.objects.create_user(
            email="instructor@test.com",
            password="testpass123",
            role="instructor",
            tenant=self.tenant
        )
        self.learner = User.objects.create_user(
            email="learner@test.com",
            password="testpass123",
            role="learner",
            tenant=self.tenant
        )
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            slug="test-course",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED
        )

    def test_generate_report_data_unknown_slug(self):
        """Test that unknown report slug raises error."""
        report = Report.objects.create(
            name="Unknown Report",
            slug="unknown-report",
            tenant=self.tenant
        )

        with self.assertRaises(ReportGenerationError):
            ReportGeneratorService.generate_report_data(report, {})

    def test_generate_course_completion_report(self):
        """Test generating course completion report."""
        report = Report.objects.create(
            name="Course Completion",
            slug="course-completion-rates",
            tenant=self.tenant
        )
        
        # Create enrollments with different statuses
        for i in range(5):
            user = User.objects.create_user(
                email=f"learner{i}@test.com",
                password="testpass123",
                role="learner",
                tenant=self.tenant
            )
            Enrollment.objects.create(
                user=user,
                course=self.course,
                status=Enrollment.Status.COMPLETED if i < 2 else Enrollment.Status.ACTIVE
            )

        result = ReportGeneratorService.generate_report_data(report, {})

        self.assertEqual(result["report_slug"], "course-completion-rates")
        self.assertIn("data", result)
        self.assertEqual(len(result["data"]), 1)
        self.assertEqual(result["data"][0]["total_enrollments"], 5)
        self.assertEqual(result["data"][0]["completed_enrollments"], 2)
        self.assertEqual(result["data"][0]["completion_rate"], 40.0)

    def test_generate_course_completion_report_filtered_by_instructor(self):
        """Test course completion report filtered by instructor."""
        report = Report.objects.create(
            name="Course Completion",
            slug="course-completion-rates",
            tenant=self.tenant
        )
        
        # Create another instructor with their own course
        other_instructor = User.objects.create_user(
            email="other@test.com",
            password="testpass123",
            role="instructor",
            tenant=self.tenant
        )
        other_course = Course.objects.create(
            tenant=self.tenant,
            title="Other Course",
            slug="other-course",
            instructor=other_instructor,
            status=Course.Status.PUBLISHED
        )
        
        # Enrollments for main instructor's course
        for i in range(3):
            user = User.objects.create_user(
                email=f"learner{i}@test.com",
                password="testpass123",
                role="learner",
                tenant=self.tenant
            )
            Enrollment.objects.create(user=user, course=self.course, status=Enrollment.Status.ACTIVE)
        
        # Enrollments for other instructor's course
        for i in range(2):
            user = User.objects.create_user(
                email=f"other_learner{i}@test.com",
                password="testpass123",
                role="learner",
                tenant=self.tenant
            )
            Enrollment.objects.create(user=user, course=other_course, status=Enrollment.Status.ACTIVE)

        # Filter by main instructor
        result = ReportGeneratorService.generate_report_data(
            report, {"instructor": str(self.instructor.id)}
        )

        self.assertEqual(len(result["data"]), 1)
        self.assertEqual(result["data"][0]["course_title"], "Test Course")

    def test_generate_user_activity_report(self):
        """Test generating user activity report."""
        report = Report.objects.create(
            name="User Activity",
            slug="user-activity-summary",
            tenant=self.tenant
        )
        
        # Create events for the learner
        Event.objects.create(
            user=self.learner,
            event_type="USER_LOGIN",
            tenant=self.tenant
        )
        Event.objects.create(
            user=self.learner,
            event_type="USER_LOGIN",
            tenant=self.tenant
        )
        Event.objects.create(
            user=self.learner,
            event_type="CONTENT_VIEW",
            tenant=self.tenant
        )

        result = ReportGeneratorService.generate_report_data(report, {})

        self.assertEqual(result["report_slug"], "user-activity-summary")
        self.assertEqual(len(result["data"]), 1)
        self.assertEqual(result["data"][0]["login_count"], 2)
        self.assertEqual(result["data"][0]["content_view_count"], 1)

    def test_generate_assessment_scores_report(self):
        """Test generating assessment scores report."""
        report = Report.objects.create(
            name="Assessment Scores",
            slug="assessment-average-scores",
            tenant=self.tenant
        )
        
        # Create assessment and attempts
        assessment = Assessment.objects.create(
            course=self.course,
            title="Test Assessment",
            assessment_type=Assessment.AssessmentType.QUIZ,
            pass_mark_percentage=70
        )
        
        for i, score in enumerate([80, 90, 70]):
            user = User.objects.create_user(
                email=f"learner{i}@test.com",
                password="testpass123",
                role="learner",
                tenant=self.tenant
            )
            Enrollment.objects.create(user=user, course=self.course, status=Enrollment.Status.ACTIVE)
            AssessmentAttempt.objects.create(
                assessment=assessment,
                user=user,
                score=Decimal(str(score)),
                is_passed=score >= 70,
                status=AssessmentAttempt.AttemptStatus.GRADED,
                end_time=timezone.now()
            )

        result = ReportGeneratorService.generate_report_data(report, {})

        self.assertEqual(result["report_slug"], "assessment-average-scores")
        self.assertEqual(len(result["data"]), 1)
        self.assertEqual(result["data"][0]["attempt_count"], 3)
        self.assertEqual(result["data"][0]["pass_rate"], 100.0)  # All passed
        self.assertEqual(result["data"][0]["average_score"], 80.0)  # (80+90+70)/3

    def test_generate_student_progress_report(self):
        """Test generating student progress report."""
        # Use get_or_create since this slug may exist from migrations
        report, _ = Report.objects.get_or_create(
            slug="student-progress",
            defaults={
                "name": "Student Progress",
                "tenant": self.tenant
            }
        )
        
        Enrollment.objects.create(
            user=self.learner,
            course=self.course,
            status=Enrollment.Status.ACTIVE
        )

        result = ReportGeneratorService.generate_report_data(report, {})

        self.assertEqual(result["report_slug"], "student-progress")
        self.assertGreaterEqual(len(result["data"]), 1)  # May have more from other tests

    def test_generate_instructor_dashboard_report_missing_instructor_id(self):
        """Test instructor dashboard report returns empty data when no instructor_id (admin view)."""
        # Use get_or_create since this slug may exist from migrations
        report, _ = Report.objects.get_or_create(
            slug="instructor-dashboard",
            defaults={
                "name": "Instructor Dashboard",
                "tenant": self.tenant
            }
        )

        # Without instructor_id, should return empty/default structure for admin view
        result = ReportGeneratorService.generate_report_data(report, {})
        
        self.assertIn("data", result)
        # Should have the expected structure with default/empty values
        self.assertIn("overview", result["data"])
        self.assertIn("ai_insights", result["data"])
        self.assertIn("predictive_analytics", result["data"])
        self.assertIn("real_time", result["data"])

    def test_apply_common_filters_date_range(self):
        """Test applying date range filters."""
        # Create events on different dates (created_at is auto_now_add, so update after creation)
        e1 = Event.objects.create(
            user=self.learner,
            event_type="USER_LOGIN",
            tenant=self.tenant
        )
        Event.objects.filter(pk=e1.pk).update(created_at=timezone.now() - timedelta(days=10))
        
        e2 = Event.objects.create(
            user=self.learner,
            event_type="USER_LOGIN",
            tenant=self.tenant
        )
        Event.objects.filter(pk=e2.pk).update(created_at=timezone.now() - timedelta(days=5))
        
        e3 = Event.objects.create(
            user=self.learner,
            event_type="USER_LOGIN",
            tenant=self.tenant
        )
        # e3 stays at "now" - no update needed

        queryset = Event.objects.all()
        filtered = ReportGeneratorService._apply_common_filters(
            queryset,
            {
                "start_date": (timezone.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
                "end_date": (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            }
        )

        self.assertEqual(filtered.count(), 2)  # Only events within date range

    def test_apply_common_filters_invalid_date(self):
        """Test applying invalid date filter raises error."""
        queryset = Event.objects.all()

        with self.assertRaises(ReportGenerationError):
            ReportGeneratorService._apply_common_filters(
                queryset,
                {"start_date": "invalid-date"}
            )


class ExportServiceTestCase(TestCase):
    """Tests for ExportService."""

    def test_export_to_csv_empty_data(self):
        """Test exporting empty data to CSV."""
        result = ExportService.export_report_to_csv([])
        self.assertEqual(result, "")

    def test_export_to_csv_with_data(self):
        """Test exporting data to CSV."""
        data = [
            {"name": "Course 1", "enrollments": 100, "completion_rate": 75.5},
            {"name": "Course 2", "enrollments": 50, "completion_rate": 80.0},
        ]

        result = ExportService.export_report_to_csv(data)

        self.assertIn("name,enrollments,completion_rate", result)
        self.assertIn("Course 1,100,75.5", result)
        self.assertIn("Course 2,50,80.0", result)

    def test_export_to_json_with_data(self):
        """Test exporting data to JSON."""
        data = [
            {"name": "Course 1", "revenue": Decimal("100.50")},
        ]

        result = ExportService.export_report_to_json(data)

        self.assertIn('"name": "Course 1"', result)
        self.assertIn('"revenue": 100.5', result)

    def test_export_to_json_handles_uuid(self):
        """Test exporting data with UUID to JSON."""
        test_uuid = uuid.uuid4()
        data = [{"id": test_uuid}]

        result = ExportService.export_report_to_json(data)

        self.assertIn(str(test_uuid), result)


class VisualizationServiceTestCase(TestCase):
    """Tests for VisualizationService."""

    def test_get_chart_config_course_completion_rates(self):
        """Test getting chart config for course completion rates."""
        data = [
            {"course_title": "Course 1", "completion_rate": 75},
            {"course_title": "Course 2", "completion_rate": 80},
        ]

        config = VisualizationService.get_chart_config("course-completion-rates", data)

        self.assertEqual(config["type"], "bar")
        self.assertIn("data", config)
        self.assertEqual(config["data"]["labels"], ["Course 1", "Course 2"])
        self.assertEqual(config["data"]["datasets"][0]["data"], [75, 80])

    def test_get_chart_config_assessment_scores(self):
        """Test getting chart config for assessment scores."""
        data = [
            {"assessment_title": "Quiz 1", "average_score": 85, "pass_rate": 90},
        ]

        config = VisualizationService.get_chart_config("assessment-average-scores", data)

        self.assertEqual(config["type"], "bar")
        self.assertEqual(len(config["data"]["datasets"]), 2)  # Score and pass rate

    def test_get_chart_config_unknown_report_defaults_to_table(self):
        """Test that unknown report slug defaults to table configuration."""
        data = [
            {"column1": "value1", "column2": "value2"},
        ]

        config = VisualizationService.get_chart_config("unknown-report", data)

        self.assertEqual(config["type"], "table")
        self.assertEqual(config["data"], data)


class DataProcessorServiceTestCase(TestCase):
    """Tests for DataProcessorService."""

    def setUp(self):
        """Set up test data."""
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant",
            is_active=True
        )
        self.instructor = User.objects.create_user(
            email="instructor@test.com",
            password="testpass123",
            role="instructor",
            tenant=self.tenant
        )
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            slug="test-course",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED
        )

    @patch.object(AnalyticsService, 'process_student_engagement_metrics')
    @patch.object(AnalyticsService, 'process_course_analytics')
    @patch.object(AnalyticsService, 'process_instructor_analytics')
    @patch.object(AnalyticsService, 'generate_ai_insights')
    @patch.object(AnalyticsService, 'generate_predictive_analytics')
    def test_process_daily_analytics_calls_all_services(
        self,
        mock_predictive,
        mock_ai,
        mock_instructor,
        mock_course,
        mock_engagement
    ):
        """Test that daily analytics processing calls all required services."""
        yesterday = timezone.now().date() - timedelta(days=1)

        DataProcessorService.process_daily_analytics(self.tenant, yesterday)

        mock_engagement.assert_called_once_with(self.tenant, yesterday)
        mock_course.assert_called_once_with(self.tenant, yesterday)
        mock_instructor.assert_called_once_with(self.tenant, yesterday)

    @patch.object(AnalyticsService, 'update_real_time_metrics')
    def test_process_real_time_metrics(self, mock_update):
        """Test processing real-time metrics for all instructors."""
        DataProcessorService.process_real_time_metrics(self.tenant)

        mock_update.assert_called_once_with(self.tenant, self.instructor.id)

    @patch.object(DataProcessorService, 'process_daily_analytics')
    def test_aggregate_daily_metrics_processes_all_tenants(self, mock_process):
        """Test that aggregate processes all active tenants."""
        # Create another active tenant
        tenant2 = Tenant.objects.create(
            name="Tenant 2",
            slug="tenant-2",
            is_active=True
        )
        # Create inactive tenant
        Tenant.objects.create(
            name="Inactive",
            slug="inactive",
            is_active=False
        )

        DataProcessorService.aggregate_daily_metrics()

        # Should be called for both active tenants
        self.assertEqual(mock_process.call_count, 2)
