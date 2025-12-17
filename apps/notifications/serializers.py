from rest_framework import serializers

from apps.courses.models import Course

from .models import (
    Announcement,
    DeliveryMethod,
    Notification,
    NotificationPreference,
    NotificationType,
    UserDevice,
)


class NotificationSerializer(serializers.ModelSerializer):
    recipient_email = serializers.EmailField(source="recipient.email", read_only=True)
    notification_type_display = serializers.CharField(
        source="get_notification_type_display", read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Notification
        fields = (
            "id",
            "recipient",
            "recipient_email",
            "notification_type",
            "notification_type_display",
            "status",
            "status_display",
            "subject",
            "message",
            "action_url",
            "sent_at",
            "read_at",
            "created_at",
        )
        read_only_fields = (
            fields  # Notifications generally read-only via API, created by system
        )


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    # Expose preferences in a structured way if needed, or just the raw JSON
    class Meta:
        model = NotificationPreference
        fields = ("id", "user", "is_enabled", "preferences", "updated_at")
        read_only_fields = ("id", "user", "updated_at")  # User cannot change user link


class NotificationPreferenceUpdateSerializer(serializers.Serializer):
    """Serializer for updating specific preferences."""

    # Example: Allow updating preferences for a specific type and method
    # Or allow updating the whole JSON blob? Updating blob is simpler for API.
    is_enabled = serializers.BooleanField(required=False)
    preferences = serializers.JSONField(required=False)

    def validate_preferences(self, value):
        # Add validation for the structure of the preferences JSON
        if not isinstance(value, dict):
            raise serializers.ValidationError("Preferences must be a dictionary.")
        for type_key, method_prefs in value.items():
            if type_key not in NotificationType.values:
                raise serializers.ValidationError(
                    f"Invalid notification type key: {type_key}"
                )
            if not isinstance(method_prefs, dict):
                raise serializers.ValidationError(
                    f"Preferences for {type_key} must be a dictionary."
                )
            for method_key, enabled_val in method_prefs.items():
                if method_key not in DeliveryMethod.values:
                    raise serializers.ValidationError(
                        f"Invalid delivery method key: {method_key} for type {type_key}"
                    )
                if not isinstance(enabled_val, bool):
                    raise serializers.ValidationError(
                        f"Preference value for {method_key} (type {type_key}) must be boolean."
                    )
        return value


class UserDeviceSerializer(serializers.ModelSerializer):
    """Serializer for device registration for push notifications."""
    
    device_type_display = serializers.CharField(
        source="get_device_type_display", read_only=True
    )
    
    class Meta:
        model = UserDevice
        fields = (
            "id",
            "device_type",
            "device_type_display",
            "token",
            "device_name",
            "is_active",
            "last_used_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "last_used_at", "created_at", "updated_at")

    def validate_token(self, value):
        """Ensure token is not empty."""
        if not value or not value.strip():
            raise serializers.ValidationError("Device token cannot be empty.")
        return value.strip()
    
    def create(self, validated_data):
        """Handle device registration, updating existing token if necessary."""
        user = self.context['request'].user
        token = validated_data.get('token')
        
        # Check if this token already exists for this user
        existing = UserDevice.objects.filter(user=user, token=token).first()
        if existing:
            # Update existing device entry
            existing.device_type = validated_data.get('device_type', existing.device_type)
            existing.device_name = validated_data.get('device_name', existing.device_name)
            existing.is_active = True  # Reactivate if previously deactivated
            existing.save()
            return existing
        
        # Create new device entry
        validated_data['user'] = user
        return super().create(validated_data)


class AnnouncementSerializer(serializers.ModelSerializer):
    """Serializer for admin announcements."""
    
    author_email = serializers.EmailField(source="author.email", read_only=True)
    target_type_display = serializers.CharField(
        source="get_target_type_display", read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    target_course_title = serializers.CharField(
        source="target_course.title", read_only=True
    )
    
    class Meta:
        model = Announcement
        fields = (
            "id",
            "tenant",
            "author",
            "author_email",
            "title",
            "message",
            "target_type",
            "target_type_display",
            "target_course",
            "target_course_title",
            "target_user_ids",
            "status",
            "status_display",
            "scheduled_at",
            "sent_at",
            "recipients_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "author",
            "author_email",
            "target_type_display",
            "status_display",
            "target_course_title",
            "sent_at",
            "recipients_count",
            "created_at",
            "updated_at",
        )
    
    def validate(self, data):
        """Validate announcement based on target type."""
        target_type = data.get('target_type', getattr(self.instance, 'target_type', None))
        
        if target_type == Announcement.TargetType.COURSE_ENROLLED:
            target_course = data.get('target_course', getattr(self.instance, 'target_course', None))
            if not target_course:
                raise serializers.ValidationError({
                    'target_course': 'A course must be specified for COURSE_ENROLLED target type.'
                })
        
        elif target_type == Announcement.TargetType.SPECIFIC_USERS:
            target_user_ids = data.get('target_user_ids', getattr(self.instance, 'target_user_ids', None))
            if not target_user_ids:
                raise serializers.ValidationError({
                    'target_user_ids': 'User IDs must be specified for SPECIFIC_USERS target type.'
                })
        
        return data
    
    def validate_target_course(self, value):
        """Ensure target course belongs to the same tenant."""
        if value:
            request = self.context.get('request')
            if request and hasattr(request, 'tenant'):
                if value.tenant != request.tenant:
                    raise serializers.ValidationError(
                        "Target course must belong to the same tenant."
                    )
        return value
