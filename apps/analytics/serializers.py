from rest_framework import serializers

from .models import (
    Event,
    Report,
    Dashboard,
    DashboardWidget,
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


class InstructorReportSerializer(serializers.ModelSerializer):
    """
    Serializer for instructor report listing.
    Maps backend fields to frontend expected format.
    """
    title = serializers.CharField(source="name", read_only=True)
    type = serializers.CharField(source="slug", read_only=True)
    generated_at = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = Report
        fields = (
            "id",
            "title",
            "type",
            "generated_at",
        )
        read_only_fields = fields


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


class DashboardWidgetSerializer(serializers.ModelSerializer):
    """Serializer for dashboard widgets."""
    widget_type_display = serializers.CharField(source="get_widget_type_display", read_only=True)
    data_source_display = serializers.CharField(source="get_data_source_display", read_only=True)

    class Meta:
        model = DashboardWidget
        fields = (
            "id",
            "widget_type",
            "widget_type_display",
            "title",
            "data_source",
            "data_source_display",
            "config",
            "position_x",
            "position_y",
            "width",
            "height",
            "order",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "widget_type_display", "data_source_display", "created_at", "updated_at")


class DashboardListSerializer(serializers.ModelSerializer):
    """Serializer for listing dashboards with minimal data."""
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    owner_name = serializers.SerializerMethodField()
    widget_count = serializers.SerializerMethodField()

    class Meta:
        model = Dashboard
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "is_default",
            "is_shared",
            "default_time_range",
            "tenant",
            "tenant_name",
            "owner",
            "owner_name",
            "widget_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_owner_name(self, obj):
        if obj.owner:
            return obj.owner.get_full_name() or obj.owner.email
        return None

    def get_widget_count(self, obj):
        return obj.widgets.count()


class DashboardDetailSerializer(serializers.ModelSerializer):
    """Serializer for dashboard detail with all widgets."""
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    owner_name = serializers.SerializerMethodField()
    widgets = DashboardWidgetSerializer(many=True, read_only=True)

    class Meta:
        model = Dashboard
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "layout_config",
            "is_default",
            "is_shared",
            "allowed_roles",
            "refresh_interval",
            "default_time_range",
            "tenant",
            "tenant_name",
            "owner",
            "owner_name",
            "widgets",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "tenant", "tenant_name", "owner_name", "widgets", "created_at", "updated_at")

    def get_owner_name(self, obj):
        if obj.owner:
            return obj.owner.get_full_name() or obj.owner.email
        return None


class DashboardCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating and updating dashboards."""
    widgets = DashboardWidgetSerializer(many=True, required=False)

    class Meta:
        model = Dashboard
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "layout_config",
            "is_default",
            "is_shared",
            "allowed_roles",
            "refresh_interval",
            "default_time_range",
            "widgets",
        )
        read_only_fields = ("id",)

    def create(self, validated_data):
        widgets_data = validated_data.pop("widgets", [])
        request = self.context.get("request")
        
        # Set tenant and owner from request
        validated_data["tenant"] = request.user.tenant
        validated_data["owner"] = request.user
        
        dashboard = Dashboard.objects.create(**validated_data)
        
        # Create widgets
        for widget_data in widgets_data:
            DashboardWidget.objects.create(dashboard=dashboard, **widget_data)
        
        return dashboard

    def update(self, instance, validated_data):
        widgets_data = validated_data.pop("widgets", None)
        
        # Update dashboard fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Update widgets if provided
        if widgets_data is not None:
            # Delete existing widgets and recreate
            instance.widgets.all().delete()
            for widget_data in widgets_data:
                DashboardWidget.objects.create(dashboard=instance, **widget_data)
        
        return instance


class WidgetCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating individual widgets."""

    class Meta:
        model = DashboardWidget
        fields = (
            "id",
            "widget_type",
            "title",
            "data_source",
            "config",
            "position_x",
            "position_y",
            "width",
            "height",
            "order",
        )
        read_only_fields = ("id",)


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


# Custom field that accepts either a list or a dict for flexible report data
class FlexibleDataField(serializers.Field):
    """
    A field that accepts either a list of dicts or a dict.
    This allows reports to return either tabular data (list) or structured data (dict).
    """
    def to_representation(self, value):
        # Pass through the value as-is since it's already Python data
        return value
    
    def to_internal_value(self, data):
        if isinstance(data, (list, dict)):
            return data
        raise serializers.ValidationError("Expected a list or dict.")


# Serializer for returning report data
class ReportDataSerializer(serializers.Serializer):
    # Structure depends entirely on the report being generated
    # Example for completion rates:
    report_slug = serializers.SlugField()
    generated_at = serializers.DateTimeField()
    filters_applied = (
        serializers.DictField()
    )  # e.g., {'course_id': 'uuid', 'date_range': '...'}
    data = FlexibleDataField()  # Can be list or dict depending on report type
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


# Event Log Serializer for Admin Event Viewer
class EventLogSerializer(serializers.ModelSerializer):
    """Detailed serializer for event log viewer with user and metadata."""
    
    user_email = serializers.CharField(source='user.email', read_only=True, allow_null=True)
    user_name = serializers.SerializerMethodField()
    event_type_display = serializers.CharField(source='get_event_type_display', read_only=True)
    
    class Meta:
        model = Event
        fields = [
            'id',
            'event_type',
            'event_type_display',
            'user',
            'user_email',
            'user_name',
            'tenant',
            'context_data',
            'session_id',
            'ip_address',
            'device_type',
            'browser',
            'os',
            'country',
            'region',
            'created_at',
        ]
        read_only_fields = fields
    
    def get_user_name(self, obj):
        if obj.user:
            return obj.user.get_full_name() or obj.user.email
        return None
