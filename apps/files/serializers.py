from rest_framework import serializers

from .models import File, Folder  # FileVersion might not need API exposure directly


class FolderSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    parent_id = serializers.UUIDField(
        source="parent.id", allow_null=True, required=False
    )

    class Meta:
        model = Folder
        fields = (
            "id",
            "name",
            "parent_id",
            "tenant",
            "tenant_name",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "tenant", "tenant_name", "created_at", "updated_at")

    def validate_parent_id(self, value):
        """Ensure parent folder exists and belongs to the same tenant."""
        if value:
            tenant = self.context["request"].tenant
            if not Folder.objects.filter(id=value, tenant=tenant).exists():
                raise serializers.ValidationError(
                    "Parent folder not found or doesn't belong to this tenant."
                )
        return value

    def create(self, validated_data):
        tenant = self.context["request"].tenant
        if not tenant:
            raise serializers.ValidationError("Tenant context required.")
        validated_data["tenant"] = tenant
        # Handle parent assignment (parent_id validated already)
        parent_id = validated_data.pop("parent_id", None)
        if parent_id:
            validated_data["parent_id"] = parent_id
        return super().create(validated_data)


class FileSerializer(serializers.ModelSerializer):
    # Use FileField for uploads, CharField(read_only=True) for URL display
    # file = serializers.FileField(write_only=True, required=True) # For upload endpoint
    file_url = serializers.URLField(read_only=True)  # For retrieving file info
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    folder_id = serializers.UUIDField(
        source="folder.id", allow_null=True, required=False
    )  # Writable to assign folder
    uploaded_by_email = serializers.EmailField(
        source="uploaded_by.email", read_only=True, allow_null=True
    )

    class Meta:
        model = File
        fields = (
            "id",
            "original_filename",
            "file_url",  # Use 'file' field for upload endpoint
            "file_size",
            "mime_type",
            "status",
            "error_message",
            "folder_id",
            "tenant",
            "tenant_name",
            "uploaded_by_email",
            "metadata",
            "scan_result",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "file_url",
            "file_size",
            "mime_type",
            "status",
            "error_message",
            "tenant",
            "tenant_name",
            "uploaded_by_email",
            "metadata",
            "scan_result",
            "created_at",
            "updated_at",
        )
        # Make fields writable as needed for specific update scenarios (e.g., assigning folder)


class FileUploadSerializer(serializers.Serializer):
    """Serializer specifically for handling file uploads."""

    file = serializers.FileField(required=True)
    folder_id = serializers.UUIDField(required=False, allow_null=True)

    def validate_folder_id(self, value):
        """Ensure folder exists and belongs to the tenant."""
        if value:
            tenant = self.context["request"].tenant
            if not Folder.objects.filter(id=value, tenant=tenant).exists():
                raise serializers.ValidationError(
                    "Folder not found or doesn't belong to this tenant."
                )
        return value

    # Save logic will be handled in the view/service using this serializer
