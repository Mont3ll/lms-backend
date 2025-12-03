from rest_framework import serializers

from .models import (
    Event,
    Report,
    Dashboard,
    StudentEngagementMetric,
    CourseAnalytics,
    InstructorAnalytics,
    PredictiveAnalytics,
    AIInsights,
    RealTimeMetrics,
    LearningEfficiency,
    SocialLearningMetrics,
    StudentPerformance,
    EngagementMetrics,
    AssessmentAnalytics,
    LearningPathProgress,
    ContentInteraction,
    CourseCompletion,
    LearningObjectiveProgress,
    RevenueAnalytics,
    DeviceUsageAnalytics,
    GeographicAnalytics,
)


# Serializer for event logging (usually internal, maybe exposed for frontend tracking)
class EventSerializer(serializers.ModelSerializer):
    # Make fields writable for creation via API if needed
    event_type = serializers.ChoiceField(choices=Event.EVENT_TYPES)
    user_id = serializers.UUIDField(source="user.id", required=False, allow_null=True)
    tenant_id = serializers.UUIDField(
        source="tenant.id", required=False, allow_null=True
    )

    class Meta:
        model = Event
        fields = (
            "id",
            "event_type",
            "user_id",
            "tenant_id",
            "context_data",
            "session_id",
            "ip_address",
            "created_at",
        )
        read_only_fields = (
            "id",
            "created_at",
        )  # Most fields set by context or logging service


# Serializers for managing report/dashboard definitions
class ReportSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(
        source="tenant.name", read_only=True, allow_null=True
    )

    class Meta:
        model = Report
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "config",
            "tenant",
            "tenant_name",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "tenant", "tenant_name", "created_at", "updated_at")


class DashboardSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)

    class Meta:
        model = Dashboard
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "layout_config",
            "tenant",
            "tenant_name",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "tenant", "tenant_name", "created_at", "updated_at")


# Student Engagement Metric Serializer
class StudentEngagementMetricSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentEngagementMetric
        fields = "__all__"


# Course Analytics Serializer
class CourseAnalyticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourseAnalytics
        fields = "__all__"


# Instructor Analytics Serializer
class InstructorAnalyticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = InstructorAnalytics
        fields = "__all__"


# Predictive Analytics Serializer
class PredictiveAnalyticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PredictiveAnalytics
        fields = "__all__"


# AI Insights Serializer
class AIInsightsSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIInsights
        fields = "__all__"


# Real Time Metrics Serializer
class RealTimeMetricsSerializer(serializers.ModelSerializer):
    class Meta:
        model = RealTimeMetrics
        fields = "__all__"


# Learning Efficiency Serializer
class LearningEfficiencySerializer(serializers.ModelSerializer):
    class Meta:
        model = LearningEfficiency
        fields = "__all__"


# Social Learning Metrics Serializer
class SocialLearningMetricsSerializer(serializers.ModelSerializer):
    class Meta:
        model = SocialLearningMetrics
        fields = "__all__"


# Serializer for returning report data
class ReportDataSerializer(serializers.Serializer):
    # Structure depends entirely on the report being generated
    # Example for completion rates:
    report_slug = serializers.SlugField()
    generated_at = serializers.DateTimeField()
    filters_applied = (
        serializers.DictField()
    )  # e.g., {'course_id': 'uuid', 'date_range': '...'}
    data = serializers.ListField(
        child=serializers.DictField()
    )  # e.g., [{'course_id': 'uuid', 'completion_rate': 0.85}, ...]
    # Could include summary statistics
    summary = serializers.DictField(required=False)


# New comprehensive serializers

# Student Performance Serializer
class StudentPerformanceSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.get_full_name', read_only=True)
    course_title = serializers.CharField(source='course.title', read_only=True)
    
    class Meta:
        model = StudentPerformance
        fields = '__all__'
        read_only_fields = ('tenant', 'last_activity')

# Engagement Metrics Serializer
class EngagementMetricsSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.get_full_name', read_only=True)
    course_title = serializers.CharField(source='course.title', read_only=True)
    
    class Meta:
        model = EngagementMetrics
        fields = '__all__'
        read_only_fields = ('tenant',)

# Assessment Analytics Serializer
class AssessmentAnalyticsSerializer(serializers.ModelSerializer):
    assessment_title = serializers.CharField(source='assessment.title', read_only=True)
    course_title = serializers.CharField(source='course.title', read_only=True)
    
    class Meta:
        model = AssessmentAnalytics
        fields = '__all__'
        read_only_fields = ('tenant',)

# Learning Path Progress Serializer
class LearningPathProgressSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.get_full_name', read_only=True)
    learning_path_title = serializers.CharField(source='learning_path.title', read_only=True)
    
    class Meta:
        model = LearningPathProgress
        fields = '__all__'
        read_only_fields = ('tenant',)

# Content Interaction Serializer
class ContentInteractionSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.get_full_name', read_only=True)
    course_title = serializers.CharField(source='course.title', read_only=True)
    
    class Meta:
        model = ContentInteraction
        fields = '__all__'
        read_only_fields = ('tenant',)

# Course Completion Serializer
class CourseCompletionSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.get_full_name', read_only=True)
    course_title = serializers.CharField(source='course.title', read_only=True)
    
    class Meta:
        model = CourseCompletion
        fields = '__all__'
        read_only_fields = ('tenant',)

# Learning Objective Progress Serializer
class LearningObjectiveProgressSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.get_full_name', read_only=True)
    course_title = serializers.CharField(source='course.title', read_only=True)
    objective_title = serializers.CharField(source='learning_objective.title', read_only=True)
    
    class Meta:
        model = LearningObjectiveProgress
        fields = '__all__'
        read_only_fields = ('tenant',)

# Revenue Analytics Serializer
class RevenueAnalyticsSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source='course.title', read_only=True)
    
    class Meta:
        model = RevenueAnalytics
        fields = '__all__'
        read_only_fields = ('tenant',)

# Device Usage Analytics Serializer
class DeviceUsageAnalyticsSerializer(serializers.ModelSerializer):
    total_users = serializers.SerializerMethodField()
    
    class Meta:
        model = DeviceUsageAnalytics
        fields = '__all__'
        read_only_fields = ('tenant',)
    
    def get_total_users(self, obj):
        return obj.desktop_users + obj.mobile_users + obj.tablet_users

# Geographic Analytics Serializer
class GeographicAnalyticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeographicAnalytics
        fields = '__all__'
        read_only_fields = ('tenant',)

# Comprehensive Analytics Dashboard Serializer
class InstructorAnalyticsDashboardSerializer(serializers.Serializer):
    """Serializer for the main instructor analytics dashboard data."""
    
    overview = serializers.DictField()
    course_performance = serializers.ListField()
    student_engagement = serializers.DictField()
    revenue_data = serializers.DictField()
    top_performers = serializers.DictField()
    student_distribution = serializers.ListField()
    cumulative_progress = serializers.ListField()
    activity_heatmap = serializers.ListField()
    device_usage = serializers.ListField()
    geographic_data = serializers.ListField()
    learning_paths = serializers.ListField()
    predictive_analytics = serializers.DictField()
    ai_insights = serializers.DictField()
    real_time_data = serializers.DictField()
    social_learning = serializers.DictField()
    learning_efficiency = serializers.DictField()

# Predictive Analytics Serializer
class PredictiveAnalyticsDataSerializer(serializers.Serializer):
    """Serializer for predictive analytics data."""
    
    student_at_risk = serializers.ListField()
    course_recommendations = serializers.ListField()
    revenue_forecasting = serializers.ListField()
    trends_analysis = serializers.ListField()

# AI Insights Serializer
class AIInsightsDataSerializer(serializers.Serializer):
    """Serializer for AI insights data."""
    
    key_insights = serializers.ListField()
    recommendations = serializers.ListField()
    anomalies = serializers.ListField()

# Real Time Data Serializer
class RealTimeDataSerializer(serializers.Serializer):
    """Serializer for real-time analytics data."""
    
    active_users = serializers.IntegerField()
    current_sessions = serializers.IntegerField()
    live_engagement = serializers.IntegerField()
    server_health = serializers.IntegerField()

# Social Learning Metrics Serializer
class SocialLearningDataSerializer(serializers.Serializer):
    """Serializer for social learning metrics."""
    
    discussions = serializers.ListField()
    peer_reviews = serializers.ListField()
    collaborative_projects = serializers.ListField()

# Learning Efficiency Serializer
class LearningEfficiencyDataSerializer(serializers.Serializer):
    """Serializer for learning efficiency data."""
    
    optimal_study_times = serializers.ListField()
    content_effectiveness = serializers.ListField()
    difficulty_progression = serializers.ListField()
