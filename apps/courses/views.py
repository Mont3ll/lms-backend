# Specific detailed views or custom actions can go here if needed.
# Most CRUD operations will be handled by ViewSets.

# Example: A view to get all content items for a course, flattened
from rest_framework import generics, permissions

from apps.users.permissions import IsInstructorOrAdmin  # Use appropriate permissions

from .models import ContentItem
from .serializers import ContentItemSerializer


class CourseContentListView(generics.ListAPIView):
    serializer_class = ContentItemSerializer
    permission_classes = [
        permissions.IsAuthenticated
    ]  # Or more specific like IsEnrolledOrInstructor

    def get_queryset(self):
        course_id = self.kwargs.get("course_id")
        # Add permission check: user must be enrolled or instructor/admin for this course
        # ... permission logic ...

        return (
            ContentItem.objects.filter(
                module__course_id=course_id,
                is_published=True,  # Only show published content? Or check user role?
            )
            .select_related("module")
            .order_by("module__order", "order")
        )


from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response

# Example: A view to handle content versioning
from rest_framework.views import APIView

from .models import ContentItem, ContentVersion
from .serializers import ContentVersionSerializer


class ContentItemVersionView(APIView):
    permission_classes = [
        permissions.IsAuthenticated,
        IsInstructorOrAdmin,
    ]  # Only instructors/admins can version

    def post(self, request, item_id, format=None):
        """Create a new version of a ContentItem"""
        content_item = get_object_or_404(ContentItem, pk=item_id)

        # Permission check: Ensure user can edit this content item's course
        # ... permission logic ...

        last_version_num = content_item.versions.order_by("-version_number").first()
        new_version_num = (
            (last_version_num.version_number + 1) if last_version_num else 1
        )

        # Create snapshot data
        version_data = {
            "content_item": content_item,
            "user": request.user,
            "version_number": new_version_num,
            "comment": request.data.get("comment", ""),
            "content_type": content_item.content_type,
            "text_content": content_item.text_content,
            "external_url": content_item.external_url,
            "metadata": content_item.metadata,
            # "file_version": content_item.file.current_version if content_item.file else None, # Link file version if needed
            # "assessment_snapshot": serialize_assessment(content_item.assessment) if content_item.assessment else None
        }

        version = ContentVersion.objects.create(**version_data)
        serializer = ContentVersionSerializer(version)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def get(self, request, item_id, format=None):
        """List versions for a ContentItem"""
        content_item = get_object_or_404(ContentItem, pk=item_id)
        # Permission check needed? Or allow viewing history?
        versions = content_item.versions.order_by("-version_number")
        serializer = ContentVersionSerializer(versions, many=True)
        return Response(serializer.data)
