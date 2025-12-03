from rest_framework import serializers

from .models import (
    DeliveryMethod,
    Notification,
    NotificationPreference,
    NotificationType,
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
