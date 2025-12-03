from rest_framework import serializers


# Example of a base serializer if needed, perhaps for TimestampedModel
class TimestampedSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    # Meta class should be defined in inheriting serializers
