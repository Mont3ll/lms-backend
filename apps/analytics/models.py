from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator

from apps.common.models import TimestampedModel
from apps.core.models import Tenant
from apps.users.models import User

# Import other models if directly linking events (Course, Enrollment, etc.)

# Note: Storing raw event data might lead to large tables. Consider alternatives
# like dedicated analytics databases (ClickHouse), data lakes, or external services (Segment).
# This model represents a simplified approach storing events in the primary DB.


class Event(TimestampedModel):
    """Represents a trackable event occurring within the LMS."""

    # Common Event Types (expand as needed)
    EVENT_TYPES = [
        ("USER_LOGIN", "User Login"),
        ("USER_LOGOUT", "User Logout"),
        ("USER_REGISTER", "User Registration"),
        ("COURSE_VIEW", "Course Viewed"),
        ("COURSE_ENROLL", "Course Enrollment"),
        ("COURSE_COMPLETE", "Course Completion"),
        ("MODULE_VIEW", "Module Viewed"),
        ("CONTENT_VIEW", "Content Item Viewed"),
        ("CONTENT_COMPLETE", "Content Item Completion"),
        ("ASSESSMENT_START", "Assessment Started"),
        ("ASSESSMENT_SUBMIT", "Assessment Submitted"),
        ("ASSESSMENT_PASS", "Assessment Passed"),
        ("ASSESSMENT_FAIL", "Assessment Failed"),
        ("FILE_DOWNLOAD", "File Downloaded"),
        ("CERTIFICATE_VIEW", "Certificate Viewed"),
        ("DISCUSSION_POST", "Discussion Post Created"),
        ("DISCUSSION_REPLY", "Discussion Reply Created"),
        ("PEER_REVIEW_SUBMIT", "Peer Review Submitted"),
        ("VIDEO_WATCH", "Video Watched"),
        ("VIDEO_COMPLETE", "Video Completed"),
        ("QUIZ_ATTEMPT", "Quiz Attempted"),
        ("ASSIGNMENT_SUBMIT", "Assignment Submitted"),
        ("SEARCH_QUERY", "Search Query"),
        ("PAGE_VIEW", "Page View"),
        ("SESSION_START", "Session Started"),
        ("SESSION_END", "Session Ended"),
        # Add more granular events
    ]

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="events", null=True, blank=True
    )  # Null if system-wide event
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="events"
    )  # Null if anonymous/system event
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES, db_index=True)
    timestamp = models.DateTimeField(
        auto_now_add=True, db_index=True
    )  # Use created_at from TimestampedModel

    # Store context data as JSON
    # Examples:
    # COURSE_VIEW: {'course_id': 'uuid', 'course_title': 'Intro Course'}
    # CONTENT_COMPLETE: {'content_id': 'uuid', 'content_title': 'Lesson 1', 'course_id': 'uuid', 'enrollment_id': 'uuid'}
    # ASSESSMENT_SUBMIT: {'assessment_id': 'uuid', 'attempt_id': 'uuid', 'score': 85.0}
    context_data = models.JSONField(blank=True, null=True)

    # Store session ID, IP address, user agent for more detailed analysis? (Consider privacy implications)
    session_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    device_type = models.CharField(max_length=20, null=True, blank=True)  # mobile, tablet, desktop
    browser = models.CharField(max_length=50, null=True, blank=True)
    os = models.CharField(max_length=50, null=True, blank=True)
    country = models.CharField(max_length=100, null=True, blank=True)
    region = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        user_email = self.user.email if self.user else "Anonymous/System"
        return f"{self.event_type} by {user_email} at {self.created_at.strftime('%Y-%m-%d %H:%M:%S')}"

    class Meta:
        ordering = ["-created_at"]  # Show newest events first
        indexes = [
            models.Index(fields=["tenant", "event_type", "created_at"]),
            models.Index(fields=["user", "event_type", "created_at"]),
            models.Index(fields=["device_type", "created_at"]),
            models.Index(fields=["country", "created_at"]),
        ]
        verbose_name = _("Tracked Event")
        verbose_name_plural = _("Tracked Events")


class StudentEngagementMetric(TimestampedModel):
    """Tracks student engagement metrics over time."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="engagement_metrics")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="engagement_metrics")
    course_id = models.UUIDField(db_index=True)
    
    # Engagement metrics
    daily_active_time = models.PositiveIntegerField(default=0)  # minutes
    weekly_active_time = models.PositiveIntegerField(default=0)  # minutes
    monthly_active_time = models.PositiveIntegerField(default=0)  # minutes
    
    # Activity counts
    content_views = models.PositiveIntegerField(default=0)
    video_watches = models.PositiveIntegerField(default=0)
    quiz_attempts = models.PositiveIntegerField(default=0)
    discussion_posts = models.PositiveIntegerField(default=0)
    assignments_submitted = models.PositiveIntegerField(default=0)
    
    # Performance metrics
    avg_quiz_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    completion_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # Behavioral metrics
    session_count = models.PositiveIntegerField(default=0)
    avg_session_duration = models.PositiveIntegerField(default=0)  # minutes
    last_activity_date = models.DateTimeField(null=True, blank=True)
    
    # Risk assessment
    risk_score = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    risk_factors = models.JSONField(
        blank=True, null=True, help_text="List of risk factors as JSON array"
    )
    
    # Engagement patterns
    preferred_learning_time = models.CharField(max_length=20, null=True, blank=True)  # morning, afternoon, evening
    preferred_device = models.CharField(max_length=20, null=True, blank=True)
    preferred_content_type = models.CharField(max_length=50, null=True, blank=True)
    
    date = models.DateField(db_index=True)
    
    class Meta:
        unique_together = ('tenant', 'user', 'course_id', 'date')
        ordering = ['-date', 'user']
        verbose_name = _("Student Engagement Metric")
        verbose_name_plural = _("Student Engagement Metrics")


class CourseAnalytics(TimestampedModel):
    """Aggregated analytics for courses."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="course_analytics")
    course_id = models.UUIDField(db_index=True)
    instructor_id = models.UUIDField(db_index=True)
    
    # Basic metrics
    total_enrollments = models.PositiveIntegerField(default=0)
    active_enrollments = models.PositiveIntegerField(default=0)
    completed_enrollments = models.PositiveIntegerField(default=0)
    dropped_enrollments = models.PositiveIntegerField(default=0)
    
    # Performance metrics
    avg_completion_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    avg_engagement_score = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    avg_rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    total_reviews = models.PositiveIntegerField(default=0)
    
    # Revenue metrics
    total_revenue = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    avg_revenue_per_student = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    
    # Content metrics
    total_content_items = models.PositiveIntegerField(default=0)
    avg_content_completion_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    most_viewed_content = models.JSONField(blank=True, null=True)
    least_viewed_content = models.JSONField(blank=True, null=True)
    
    # Assessment metrics
    total_assessments = models.PositiveIntegerField(default=0)
    avg_assessment_score = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    assessment_completion_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # Social learning metrics
    discussion_messages = models.PositiveIntegerField(default=0)
    discussion_participants = models.PositiveIntegerField(default=0)
    peer_reviews = models.PositiveIntegerField(default=0)
    collaborative_projects = models.PositiveIntegerField(default=0)
    
    # Time-based metrics
    avg_time_to_complete = models.PositiveIntegerField(default=0)  # days
    avg_study_time_per_week = models.PositiveIntegerField(default=0)  # minutes
    
    # Device and geographic data
    device_distribution = models.JSONField(blank=True, null=True)
    geographic_distribution = models.JSONField(blank=True, null=True)
    
    date = models.DateField(db_index=True)
    
    class Meta:
        unique_together = ('tenant', 'course_id', 'date')
        ordering = ['-date', 'course_id']
        verbose_name = _("Course Analytics")
        verbose_name_plural = _("Course Analytics")


class InstructorAnalytics(TimestampedModel):
    """Aggregated analytics for instructors."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="instructor_analytics")
    instructor_id = models.UUIDField(db_index=True)
    
    # Course metrics
    total_courses = models.PositiveIntegerField(default=0)
    published_courses = models.PositiveIntegerField(default=0)
    draft_courses = models.PositiveIntegerField(default=0)
    
    # Student metrics
    total_students = models.PositiveIntegerField(default=0)
    active_students = models.PositiveIntegerField(default=0)
    new_students = models.PositiveIntegerField(default=0)
    
    # Performance metrics
    avg_course_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    avg_completion_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    avg_engagement_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # Revenue metrics
    total_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    monthly_revenue = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    avg_revenue_per_student = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    
    # Growth metrics
    student_growth_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    revenue_growth_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # Additional dashboard metrics
    pending_grading = models.PositiveIntegerField(default=0)
    total_enrollments = models.PositiveIntegerField(default=0)
    active_enrollments = models.PositiveIntegerField(default=0)
    modules_created = models.PositiveIntegerField(default=0)
    content_items_created = models.PositiveIntegerField(default=0)
    published_this_month = models.PositiveIntegerField(default=0)
    
    date = models.DateField(db_index=True)
    
    class Meta:
        unique_together = ('tenant', 'instructor_id', 'date')
        ordering = ['-date', 'instructor_id']
        verbose_name = _("Instructor Analytics")
        verbose_name_plural = _("Instructor Analytics")


class PredictiveAnalytics(TimestampedModel):
    """Stores predictive analytics and forecasting data."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="predictive_analytics")
    instructor_id = models.UUIDField(db_index=True)
    
    # Students at risk
    students_at_risk = models.JSONField(blank=True, null=True)
    
    # Course recommendations
    course_recommendations = models.JSONField(blank=True, null=True)
    
    # Revenue forecasting
    revenue_forecast = models.JSONField(blank=True, null=True)
    
    # Trend analysis
    trends_analysis = models.JSONField(blank=True, null=True)
    
    # Confidence scores
    prediction_confidence = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Model version and metadata
    model_version = models.CharField(max_length=50, default="1.0")
    prediction_date = models.DateField(db_index=True)
    
    class Meta:
        unique_together = ('tenant', 'instructor_id', 'prediction_date')
        ordering = ['-prediction_date', 'instructor_id']
        verbose_name = _("Predictive Analytics")
        verbose_name_plural = _("Predictive Analytics")


class AIInsights(TimestampedModel):
    """Stores AI-generated insights and recommendations."""
    
    INSIGHT_TYPES = [
        ('positive', 'Positive'),
        ('negative', 'Negative'),
        ('neutral', 'Neutral'),
        ('warning', 'Warning'),
    ]
    
    PRIORITY_LEVELS = [
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ]
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="ai_insights")
    instructor_id = models.UUIDField(db_index=True)
    
    # Key insights
    key_insights = models.JSONField(blank=True, null=True)
    
    # Recommendations
    recommendations = models.JSONField(blank=True, null=True)
    
    # Anomalies detected
    anomalies = models.JSONField(blank=True, null=True)
    
    # Overall confidence score
    confidence_score = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # AI model information
    ai_model = models.CharField(max_length=100, default="default")
    model_version = models.CharField(max_length=50, default="1.0")
    
    date = models.DateField(db_index=True)
    
    class Meta:
        unique_together = ('tenant', 'instructor_id', 'date')
        ordering = ['-date', 'instructor_id']
        verbose_name = _("AI Insights")
        verbose_name_plural = _("AI Insights")


class RealTimeMetrics(TimestampedModel):
    """Stores real-time metrics for live dashboard."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="realtime_metrics")
    instructor_id = models.UUIDField(db_index=True)
    
    # Real-time counters
    active_users = models.PositiveIntegerField(default=0)
    current_sessions = models.PositiveIntegerField(default=0)
    live_engagement_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # System health
    server_health = models.DecimalField(max_digits=5, decimal_places=2, default=100)
    response_time = models.PositiveIntegerField(default=0)  # milliseconds
    
    # Current activity
    current_course_views = models.PositiveIntegerField(default=0)
    current_video_watches = models.PositiveIntegerField(default=0)
    current_quiz_attempts = models.PositiveIntegerField(default=0)
    
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name = _("Real-Time Metrics")
        verbose_name_plural = _("Real-Time Metrics")


class LearningEfficiency(TimestampedModel):
    """Tracks learning efficiency metrics."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="learning_efficiency")
    instructor_id = models.UUIDField(db_index=True)
    course_id = models.UUIDField(db_index=True, null=True, blank=True)
    
    # Optimal study times
    optimal_study_times = models.JSONField(blank=True, null=True)
    
    # Content effectiveness
    content_effectiveness = models.JSONField(blank=True, null=True)
    
    # Difficulty progression
    difficulty_progression = models.JSONField(blank=True, null=True)
    
    # Learning patterns
    learning_patterns = models.JSONField(blank=True, null=True)
    
    date = models.DateField(db_index=True)
    
    class Meta:
        unique_together = ('tenant', 'instructor_id', 'course_id', 'date')
        ordering = ['-date', 'instructor_id']
        verbose_name = _("Learning Efficiency")
        verbose_name_plural = _("Learning Efficiency")


class SocialLearningMetrics(TimestampedModel):
    """Tracks social learning and collaboration metrics."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="social_learning_metrics")
    instructor_id = models.UUIDField(db_index=True)
    course_id = models.UUIDField(db_index=True)
    
    # Discussion metrics
    discussion_messages = models.PositiveIntegerField(default=0)
    discussion_participants = models.PositiveIntegerField(default=0)
    discussion_threads = models.PositiveIntegerField(default=0)
    
    # Peer review metrics
    peer_reviews_submitted = models.PositiveIntegerField(default=0)
    peer_reviews_received = models.PositiveIntegerField(default=0)
    avg_peer_review_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    
    # Collaborative projects
    collaborative_projects = models.PositiveIntegerField(default=0)
    project_participants = models.PositiveIntegerField(default=0)
    avg_project_completion_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # Social engagement
    study_groups = models.PositiveIntegerField(default=0)
    peer_help_requests = models.PositiveIntegerField(default=0)
    peer_help_responses = models.PositiveIntegerField(default=0)
    
    date = models.DateField(db_index=True)
    
    class Meta:
        unique_together = ('tenant', 'instructor_id', 'course_id', 'date')
        ordering = ['-date', 'instructor_id']
        verbose_name = _("Social Learning Metrics")
        verbose_name_plural = _("Social Learning Metrics")


# --- Reporting / Dashboard Models (Simplified representation) ---
# These might store definitions or cached results. Actual report generation
# would query the Event model or aggregated data.


class Report(TimestampedModel):
    """Defines a type of report that can be generated."""

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="reports", null=True, blank=True
    )  # Null for system-wide reports
    name = models.CharField(max_length=255)
    slug = models.SlugField(
        max_length=100, unique=True, help_text="Unique identifier for API access"
    )
    description = models.TextField(blank=True)
    # Configuration for the report query (e.g., event types, grouping, time range)
    config = models.JSONField(
        blank=True, null=True, help_text="Configuration for generating the report"
    )
    # Cache of last generated result? Or just definition? Let's assume definition only for now.
    # last_generated_at = models.DateTimeField(null=True, blank=True)
    # cached_data = models.JSONField(null=True, blank=True)

    def __str__(self):
        tenant_name = f" ({self.tenant.name})" if self.tenant else " (System)"
        return f"{self.name}{tenant_name}"

    class Meta:
        ordering = ["tenant__name", "name"]
        verbose_name = _("Report Definition")
        verbose_name_plural = _("Report Definitions")


class Dashboard(TimestampedModel):
    """Represents a dashboard containing multiple report widgets/visualizations."""

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="dashboards"
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    # Configuration defining layout and widgets (which reports, chart types)
    layout_config = models.JSONField(blank=True, null=True)
    # Define access control? (e.g., roles that can view this dashboard)
    # allowed_roles = models.JSONField(default=list, blank=True)

    def __str__(self):
        return f"{self.name} ({self.tenant.name})"

    class Meta:
        unique_together = ("tenant", "slug")
        ordering = ["tenant__name", "name"]
        verbose_name = _("Dashboard Definition")
        verbose_name_plural = _("Dashboard Definitions")


# Metric model might be too granular. Often metrics are calculated dynamically from events.
# If storing pre-calculated metrics:
# class Metric(TimestampedModel):
#     tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='metrics')
#     name = models.CharField(max_length=100, db_index=True) # e.g., 'daily_active_users', 'course_completion_rate'
#     value = models.DecimalField(max_digits=15, decimal_places=4)
#     timestamp = models.DateTimeField(db_index=True) # Time bucket for the metric
#     dimensions = models.JSONField(default=dict, blank=True) # e.g., {'course_id': 'uuid'}
#
#     class Meta:
#         ordering = ['-timestamp', 'name']


# Additional models for comprehensive analytics

class StudentPerformance(TimestampedModel):
    """Tracks individual student performance across courses and assessments."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='student_performances')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='performance_records')
    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='student_performances')
    assessment = models.ForeignKey('assessments.Assessment', on_delete=models.CASCADE, related_name='student_performances', null=True, blank=True)
    
    score = models.DecimalField(max_digits=5, decimal_places=2, help_text="Score achieved (0-100)")
    completion_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text="Percentage of course completed")
    time_spent = models.DurationField(help_text="Total time spent on course/assessment")
    completion_time = models.DurationField(null=True, blank=True, help_text="Time taken to complete")
    attempts = models.PositiveIntegerField(default=1, help_text="Number of attempts")
    last_activity = models.DateTimeField(auto_now=True)
    
    # Risk assessment
    risk_score = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text="Risk score (0-100)")
    risk_factors = models.JSONField(default=list, help_text="List of risk factors")
    
    class Meta:
        unique_together = ['student', 'course', 'assessment']
        ordering = ['-last_activity']
        indexes = [
            models.Index(fields=['student', 'course']),
            models.Index(fields=['risk_score']),
        ]


class EngagementMetrics(TimestampedModel):
    """Tracks student engagement metrics."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='detailed_engagement_metrics')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='detailed_engagement_metrics', null=True, blank=True)
    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='detailed_engagement_metrics')
    date = models.DateField()
    
    # Engagement data
    active_users = models.PositiveIntegerField(default=0)
    session_duration = models.DurationField(help_text="Average session duration")
    page_views = models.PositiveIntegerField(default=0)
    interactions = models.PositiveIntegerField(default=0)
    video_watch_time = models.DurationField(null=True, blank=True)
    quiz_attempts = models.PositiveIntegerField(default=0)
    forum_posts = models.PositiveIntegerField(default=0)
    
    # Device and location data
    device_type = models.CharField(max_length=50, choices=[
        ('desktop', 'Desktop'),
        ('mobile', 'Mobile'),
        ('tablet', 'Tablet'),
    ], default='desktop')
    geographic_region = models.CharField(max_length=100, blank=True)
    
    class Meta:
        unique_together = ['student', 'course', 'date']
        ordering = ['-date']


class AssessmentAnalytics(TimestampedModel):
    """Analytics data for assessments."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='assessment_analytics')
    assessment = models.ForeignKey('assessments.Assessment', on_delete=models.CASCADE, related_name='analytics')
    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='assessment_analytics')
    
    # Performance metrics
    total_attempts = models.PositiveIntegerField(default=0)
    avg_score = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    completion_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    avg_completion_time = models.DurationField(null=True, blank=True)
    
    # Difficulty analysis
    difficulty_score = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text="0-100, higher = more difficult")
    pass_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # Distribution data
    score_distribution = models.JSONField(blank=True, null=True, help_text="Score distribution buckets")
    
    class Meta:
        unique_together = ['assessment', 'tenant']
        ordering = ['-created_at']


class LearningPathProgress(TimestampedModel):
    """Tracks progress through learning paths."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='learning_path_progress')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='learning_path_progress')
    learning_path = models.ForeignKey('learning_paths.LearningPath', on_delete=models.CASCADE, related_name='progress_records')
    
    # Progress data
    completion_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    current_step = models.PositiveIntegerField(default=0)
    total_steps = models.PositiveIntegerField(default=0)
    estimated_completion_time = models.DurationField(null=True, blank=True)
    actual_time_spent = models.DurationField(null=True, blank=True)
    
    # Status
    status = models.CharField(max_length=20, choices=[
        ('not_started', 'Not Started'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('paused', 'Paused'),
        ('dropped', 'Dropped'),
    ], default='not_started')
    
    class Meta:
        unique_together = ['student', 'learning_path']
        ordering = ['-updated_at']


class ContentInteraction(TimestampedModel):
    """Tracks interactions with specific content pieces."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='content_interactions')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='content_interactions')
    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='content_interactions')
    content_type = models.CharField(max_length=50, choices=[
        ('video', 'Video'),
        ('text', 'Text'),
        ('interactive', 'Interactive'),
        ('quiz', 'Quiz'),
        ('assignment', 'Assignment'),
    ])
    content_id = models.CharField(max_length=255, help_text="ID of the specific content piece")
    
    # Interaction data
    interaction_type = models.CharField(max_length=50, choices=[
        ('view', 'View'),
        ('play', 'Play'),
        ('pause', 'Pause'),
        ('complete', 'Complete'),
        ('download', 'Download'),
        ('bookmark', 'Bookmark'),
    ])
    duration = models.DurationField(null=True, blank=True)
    completion_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # Effectiveness metrics
    was_helpful = models.BooleanField(null=True, blank=True)
    difficulty_rating = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)])
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['student', 'course']),
            models.Index(fields=['content_type', 'interaction_type']),
        ]


class CourseCompletion(TimestampedModel):
    """Tracks course completion status and metrics."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='course_completions')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='course_completions')
    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='completions')
    
    # Completion data
    completion_date = models.DateTimeField(null=True, blank=True)
    completion_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    total_time_spent = models.DurationField(null=True, blank=True)
    final_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    
    # Certification
    certificate_issued = models.BooleanField(default=False)
    certificate_date = models.DateTimeField(null=True, blank=True)
    
    # Engagement metrics
    forum_participation = models.PositiveIntegerField(default=0)
    assignment_submissions = models.PositiveIntegerField(default=0)
    peer_reviews_given = models.PositiveIntegerField(default=0)
    
    class Meta:
        unique_together = ['student', 'course']
        ordering = ['-completion_date']


class LearningObjectiveProgress(TimestampedModel):
    """Tracks progress toward specific learning objectives."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='learning_objective_progress')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='learning_objective_progress')
    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='learning_objective_progress')
    objective_title = models.CharField(max_length=255, help_text="Title of the learning objective")
    objective_description = models.TextField(blank=True, help_text="Description of the learning objective")
    
    # Progress metrics
    mastery_level = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text="Mastery percentage (0-100)")
    attempts = models.PositiveIntegerField(default=0)
    time_to_mastery = models.DurationField(null=True, blank=True)
    
    # Achievement data
    achieved = models.BooleanField(default=False)
    achievement_date = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        unique_together = ['student', 'course', 'objective_title']
        ordering = ['-updated_at']


class RevenueAnalytics(TimestampedModel):
    """Tracks revenue and financial analytics."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='revenue_analytics')
    instructor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='revenue_analytics', null=True, blank=True)
    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='revenue_analytics', null=True, blank=True)
    
    # Revenue data
    period_start = models.DateField()
    period_end = models.DateField()
    total_revenue = models.DecimalField(max_digits=10, decimal_places=2)
    enrolled_students = models.PositiveIntegerField(default=0)
    revenue_per_student = models.DecimalField(max_digits=8, decimal_places=2)
    
    # Monthly breakdown
    monthly_revenue = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    avg_per_course = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    growth_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text="Growth rate percentage")
    
    # Forecasting
    predicted_revenue = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    confidence_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    
    class Meta:
        unique_together = ['course', 'period_start', 'period_end']
        ordering = ['-period_end']


class DeviceUsageAnalytics(TimestampedModel):
    """Tracks device usage patterns."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='device_usage_analytics')
    date = models.DateField()
    
    # Device data
    desktop_users = models.PositiveIntegerField(default=0)
    mobile_users = models.PositiveIntegerField(default=0)
    tablet_users = models.PositiveIntegerField(default=0)
    
    # Usage patterns
    desktop_session_duration = models.DurationField(null=True, blank=True)
    mobile_session_duration = models.DurationField(null=True, blank=True)
    tablet_session_duration = models.DurationField(null=True, blank=True)
    
    class Meta:
        unique_together = ['tenant', 'date']
        ordering = ['-date']


class GeographicAnalytics(TimestampedModel):
    """Tracks geographic distribution of students."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='geographic_analytics')
    region = models.CharField(max_length=100)
    country = models.CharField(max_length=100, blank=True)
    
    # Analytics data
    total_students = models.PositiveIntegerField(default=0)
    active_students = models.PositiveIntegerField(default=0)
    total_revenue = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    avg_completion_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    class Meta:
        unique_together = ['tenant', 'region']
        ordering = ['-total_students']


# Additional models for comprehensive analytics support

class DiscussionInteraction(TimestampedModel):
    """Tracks discussion forum interactions for social learning analytics."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='discussion_interactions')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='discussion_interactions')
    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='discussion_interactions')
    
    # Interaction details
    interaction_type = models.CharField(max_length=20, choices=[
        ('post', 'Post'),
        ('reply', 'Reply'),
        ('like', 'Like'),
        ('share', 'Share'),
        ('bookmark', 'Bookmark'),
        ('view', 'View'),
    ])
    
    # Content references
    discussion_id = models.CharField(max_length=255, help_text="ID of the discussion thread")
    post_id = models.CharField(max_length=255, null=True, blank=True, help_text="ID of the specific post")
    
    # Engagement metrics
    content_length = models.PositiveIntegerField(default=0, help_text="Length of content in characters")
    likes_received = models.PositiveIntegerField(default=0)
    replies_received = models.PositiveIntegerField(default=0)
    
    # Quality metrics
    quality_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Quality score (0-100)")
    helpfulness_rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True, help_text="Helpfulness rating (1-5)")
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'course']),
            models.Index(fields=['interaction_type', 'created_at']),
        ]


class PeerReview(TimestampedModel):
    """Tracks peer review activities for social learning analytics."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='peer_reviews')
    reviewer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='peer_reviews_given')
    reviewee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='peer_reviews_received')
    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='peer_reviews')
    assessment = models.ForeignKey('assessments.Assessment', on_delete=models.CASCADE, related_name='peer_reviews', null=True, blank=True)
    
    # Review details
    assignment_id = models.CharField(max_length=255, help_text="ID of the assignment being reviewed")
    rating = models.DecimalField(max_digits=3, decimal_places=2, help_text="Rating given (1-5)")
    feedback = models.TextField(help_text="Written feedback")
    
    # Quality metrics
    feedback_quality = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Quality of feedback (0-100)")
    helpfulness_rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True, help_text="How helpful was this review (1-5)")
    
    # Status
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('submitted', 'Submitted'),
        ('reviewed', 'Reviewed'),
        ('disputed', 'Disputed'),
    ], default='pending')
    
    submitted_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        unique_together = ['reviewer', 'reviewee', 'assignment_id']
        ordering = ['-created_at']


class StudySession(TimestampedModel):
    """Tracks individual study sessions for detailed analytics."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='study_sessions')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='study_sessions')
    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='study_sessions')
    
    # Session details
    session_id = models.CharField(max_length=255, unique=True, help_text="Unique session identifier")
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration = models.DurationField(null=True, blank=True, help_text="Total session duration")
    
    # Engagement metrics
    pages_visited = models.PositiveIntegerField(default=0)
    videos_watched = models.PositiveIntegerField(default=0)
    quizzes_attempted = models.PositiveIntegerField(default=0)
    downloads = models.PositiveIntegerField(default=0)
    
    # Device and context
    device_type = models.CharField(max_length=20, choices=[
        ('desktop', 'Desktop'),
        ('mobile', 'Mobile'),
        ('tablet', 'Tablet'),
    ], default='desktop')
    browser = models.CharField(max_length=50, blank=True)
    os = models.CharField(max_length=50, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    
    # Location data
    country = models.CharField(max_length=100, blank=True)
    region = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)
    
    # Quality metrics
    engagement_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Engagement score (0-100)")
    focus_time = models.DurationField(null=True, blank=True, help_text="Estimated focused study time")
    
    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['user', 'course']),
            models.Index(fields=['started_at', 'ended_at']),
            models.Index(fields=['device_type', 'started_at']),
        ]


class ActivityFeed(TimestampedModel):
    """Tracks user activities for dashboard recent activity feed."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='activity_feeds')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activity_feeds')
    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='activity_feeds', null=True, blank=True)
    
    # Activity details
    activity_type = models.CharField(max_length=50, choices=[
        ('course_enrollment', 'Course Enrollment'),
        ('course_completion', 'Course Completion'),
        ('lesson_completion', 'Lesson Completion'),
        ('assessment_submission', 'Assessment Submission'),
        ('assessment_passed', 'Assessment Passed'),
        ('discussion_post', 'Discussion Post'),
        ('assignment_submission', 'Assignment Submission'),
        ('certificate_earned', 'Certificate Earned'),
        ('badge_earned', 'Badge Earned'),
        ('peer_review_submitted', 'Peer Review Submitted'),
        ('learning_path_started', 'Learning Path Started'),
        ('learning_path_completed', 'Learning Path Completed'),
    ])
    
    # Content references
    title = models.CharField(max_length=255, help_text="Title of the activity")
    description = models.TextField(help_text="Description of the activity")
    metadata = models.JSONField(blank=True, null=True, help_text="Additional activity metadata")
    
    # Visibility and importance
    is_public = models.BooleanField(default=True, help_text="Whether this activity is visible to others")
    importance = models.CharField(max_length=10, choices=[
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ], default='medium')
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'course']),
            models.Index(fields=['activity_type', 'created_at']),
            models.Index(fields=['is_public', 'created_at']),
        ]


class NotificationMetrics(TimestampedModel):
    """Tracks notification delivery and engagement metrics."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='notification_metrics')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notification_metrics')
    
    # Notification details
    notification_type = models.CharField(max_length=50, choices=[
        ('course_reminder', 'Course Reminder'),
        ('assignment_due', 'Assignment Due'),
        ('grade_available', 'Grade Available'),
        ('discussion_reply', 'Discussion Reply'),
        ('course_update', 'Course Update'),
        ('achievement', 'Achievement'),
        ('system_alert', 'System Alert'),
    ])
    
    # Delivery metrics
    sent_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    clicked_at = models.DateTimeField(null=True, blank=True)
    
    # Channels
    channel = models.CharField(max_length=20, choices=[
        ('email', 'Email'),
        ('push', 'Push Notification'),
        ('sms', 'SMS'),
        ('in_app', 'In-App'),
    ])
    
    # Status
    status = models.CharField(max_length=20, choices=[
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('read', 'Read'),
        ('clicked', 'Clicked'),
        ('failed', 'Failed'),
        ('bounced', 'Bounced'),
    ], default='sent')
    
    class Meta:
        ordering = ['-sent_at']
        indexes = [
            models.Index(fields=['user', 'notification_type']),
            models.Index(fields=['status', 'sent_at']),
        ]


class CollaborativeProject(TimestampedModel):
    """Tracks collaborative projects for social learning analytics."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='collaborative_projects')
    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='collaborative_projects')
    
    # Project details
    title = models.CharField(max_length=255)
    description = models.TextField()
    due_date = models.DateTimeField(null=True, blank=True)
    
    # Participants
    participants = models.ManyToManyField(User, related_name='collaborative_projects')
    max_participants = models.PositiveIntegerField(default=4)
    
    # Status
    status = models.CharField(max_length=20, choices=[
        ('planning', 'Planning'),
        ('in_progress', 'In Progress'),
        ('submitted', 'Submitted'),
        ('graded', 'Graded'),
        ('completed', 'Completed'),
    ], default='planning')
    
    # Metrics
    total_contributions = models.PositiveIntegerField(default=0)
    avg_participation_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    completion_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['course', 'status']),
            models.Index(fields=['due_date', 'status']),
        ]


class StudyGroup(TimestampedModel):
    """Tracks study groups for social learning analytics."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='study_groups')
    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='study_groups')
    
    # Group details
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    
    # Members
    members = models.ManyToManyField(User, related_name='study_groups')
    max_members = models.PositiveIntegerField(default=8)
    
    # Activity metrics
    total_sessions = models.PositiveIntegerField(default=0)
    avg_session_duration = models.DurationField(null=True, blank=True)
    last_activity = models.DateTimeField(null=True, blank=True)
    
    # Status
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['course', 'is_active']),
            models.Index(fields=['last_activity']),
        ]


class LearningPathEnrollment(TimestampedModel):
    """Tracks user enrollment and progress in learning paths."""
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='learning_path_enrollments')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='learning_path_enrollments')
    learning_path = models.ForeignKey('learning_paths.LearningPath', on_delete=models.CASCADE, related_name='enrollments')
    
    # Enrollment details
    enrolled_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Progress tracking
    current_step = models.PositiveIntegerField(default=0)
    total_steps = models.PositiveIntegerField(default=0)
    completion_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # Status
    status = models.CharField(max_length=20, choices=[
        ('enrolled', 'Enrolled'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('paused', 'Paused'),
        ('dropped', 'Dropped'),
    ], default='enrolled')
    
    # Time tracking
    estimated_completion_time = models.DurationField(null=True, blank=True)
    actual_time_spent = models.DurationField(null=True, blank=True)
    
    class Meta:
        unique_together = ['user', 'learning_path']
        ordering = ['-enrolled_at']
