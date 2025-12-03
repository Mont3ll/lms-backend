import logging
import uuid
from django.utils import timezone
from rest_framework import generics, permissions, viewsets, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from .models import Notification, NotificationPreference
from .serializers import (
    NotificationSerializer,
    NotificationPreferenceSerializer,
    NotificationPreferenceUpdateSerializer
)
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

logger = logging.getLogger(__name__)

@extend_schema(tags=['Notifications'])
class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """ API endpoint for listing and managing user notifications (mark read/dismiss). """
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    # Add parameters for documentation
    @extend_schema(
        parameters=[
            OpenApiParameter(name='status', description='Filter by status (e.g., PENDING, SENT, READ)', required=False, type=OpenApiTypes.STR, enum=[s[0] for s in Notification.Status.choices]),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return Notification.objects.none()

        user = self.request.user
        if not user.is_authenticated: return Notification.objects.none()

        # Users only see their own notifications
        queryset = Notification.objects.filter(recipient=user)

        # Filter by status query param
        status_filter = self.request.query_params.get('status')
        if status_filter:
             statuses = [s.strip().upper() for s in status_filter.split(',') if s.strip()]
             valid_statuses = [choice[0] for choice in Notification.Status.choices]
             queryset = queryset.filter(status__in=[s for s in statuses if s in valid_statuses])
        else:
             # Default: Exclude dismissed? Show pending, sent, read, failed?
             queryset = queryset.exclude(status=Notification.Status.DISMISSED)

        return queryset.order_by('-created_at') # Show newest first

    @extend_schema(request=None, responses={200: NotificationSerializer})
    @action(detail=True, methods=['post'], url_path='mark-read')
    def mark_read(self, request, pk=None):
        """ Mark a specific notification as read. """
        notification = self.get_object() # Checks ownership via get_queryset filter
        updated = False
        if notification.status not in [Notification.Status.READ, Notification.Status.DISMISSED]:
            notification.status = Notification.Status.READ
            notification.read_at = timezone.now()
            notification.save(update_fields=['status', 'read_at'])
            updated = True
            logger.info(f"Notification {pk} marked as read for user {request.user.id}")
        serializer = self.get_serializer(notification)
        # Return 200 OK, serializer shows current state
        return Response(serializer.data)

    @extend_schema(request=None, responses={200: {'updated_count': OpenApiTypes.INT}})
    @action(detail=False, methods=['post'], url_path='mark-all-read')
    def mark_all_read(self, request):
        """ Mark all unread (sent/pending) notifications for the user as read. """
        # Avoid marking FAILED or DISMISSED as READ implicitly
        updated_count = Notification.objects.filter(
            recipient=request.user,
            status__in=[Notification.Status.SENT, Notification.Status.PENDING]
        ).update(status=Notification.Status.READ, read_at=timezone.now())
        logger.info(f"Marked {updated_count} notifications as read for user {request.user.id}")
        return Response({'updated_count': updated_count})

    @extend_schema(request=None, responses={200: NotificationSerializer})
    @action(detail=True, methods=['post'], url_path='dismiss')
    def dismiss(self, request, pk=None):
        """ Mark a specific notification as dismissed (hidden). """
        notification = self.get_object()
        updated = False
        if notification.status != Notification.Status.DISMISSED:
            notification.status = Notification.Status.DISMISSED
            # Optionally set read_at if dismissing an unread notification
            if not notification.read_at:
                 notification.read_at = timezone.now()
                 notification.save(update_fields=['status', 'read_at'])
            else:
                 notification.save(update_fields=['status'])
            updated = True
            logger.info(f"Notification {pk} dismissed for user {request.user.id}")
        serializer = self.get_serializer(notification)
        return Response(serializer.data)


@extend_schema(
    tags=['Notifications'],
    summary="Get/Update Notification Preferences",
    description="Retrieve or update the notification preferences for the currently authenticated user."
    # Responses defined by RetrieveUpdateAPIView default schema generation
)
class NotificationPreferenceView(generics.RetrieveUpdateAPIView):
    """ API endpoint for retrieving and updating user notification preferences. """
    # Use RetrieveUpdateAPIView which handles GET and PUT/PATCH
    serializer_class = NotificationPreferenceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        # Get or create preferences for the current user, ensuring it exists
        prefs, created = NotificationPreference.objects.get_or_create(user=self.request.user)
        if created:
             logger.info(f"Created default NotificationPreference for user {self.request.user.id}")
        return prefs

    # Use dedicated serializer for updates to control which fields are writable
    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return NotificationPreferenceUpdateSerializer
        return NotificationPreferenceSerializer

    # Perform update handles merging/saving logic
    def perform_update(self, serializer):
        instance = self.get_object()
        validated_data = serializer.validated_data

        update_fields = []
        if 'is_enabled' in validated_data:
            instance.is_enabled = validated_data['is_enabled']
            update_fields.append('is_enabled')

        if 'preferences' in validated_data:
            # PUT replaces, PATCH should ideally merge, but simple update is easier
            # Let's make PUT/PATCH both replace the 'preferences' dict for simplicity
            instance.preferences = validated_data['preferences']
            update_fields.append('preferences')

        if update_fields:
            instance.updated_at = timezone.now() # Manually update timestamp
            update_fields.append('updated_at')
            instance.save(update_fields=update_fields)
            logger.info(f"Updated notification preferences for user {self.request.user.id}")
        # Serializer used for response is NotificationPreferenceSerializer (read serializer)
