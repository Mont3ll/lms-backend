import logging
import uuid
from django.utils import timezone
from rest_framework import generics, permissions, viewsets, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from .models import Announcement, Notification, NotificationPreference, NotificationType, UserDevice
from .serializers import (
    AnnouncementSerializer,
    NotificationSerializer,
    NotificationPreferenceSerializer,
    NotificationPreferenceUpdateSerializer,
    UserDeviceSerializer,
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


@extend_schema(tags=['Notifications'])
class UserDeviceViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing user devices for push notifications.
    Users can register, list, update, and deactivate their devices.
    """
    serializer_class = UserDeviceSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Users can only see their own devices."""
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return UserDevice.objects.none()
        
        user = self.request.user
        if not user.is_authenticated:
            return UserDevice.objects.none()
        
        return UserDevice.objects.filter(user=user).order_by('-created_at')
    
    def perform_create(self, serializer):
        """Associate the device with the current user."""
        # Note: The serializer's create method handles user assignment
        # and updating existing tokens
        serializer.save()
        logger.info(f"Device registered for user {self.request.user.id}")
    
    @extend_schema(
        request=None,
        responses={200: UserDeviceSerializer},
        summary="Deactivate a device"
    )
    @action(detail=True, methods=['post'], url_path='deactivate')
    def deactivate(self, request, pk=None):
        """Deactivate a device (mark as inactive for push notifications)."""
        device = self.get_object()
        device.is_active = False
        device.save(update_fields=['is_active', 'updated_at'])
        logger.info(f"Device {pk} deactivated for user {request.user.id}")
        serializer = self.get_serializer(device)
        return Response(serializer.data)
    
    @extend_schema(
        request=None,
        responses={200: UserDeviceSerializer},
        summary="Reactivate a device"
    )
    @action(detail=True, methods=['post'], url_path='activate')
    def activate(self, request, pk=None):
        """Reactivate a previously deactivated device."""
        device = self.get_object()
        device.is_active = True
        device.save(update_fields=['is_active', 'updated_at'])
        logger.info(f"Device {pk} reactivated for user {request.user.id}")
        serializer = self.get_serializer(device)
        return Response(serializer.data)


@extend_schema(tags=['Notifications'])
class AnnouncementViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing admin announcements.
    Admins can create, update, and send announcements to targeted user groups.
    """
    serializer_class = AnnouncementSerializer
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    
    def get_queryset(self):
        """Return announcements for the current tenant."""
        # Handle schema generation request
        if getattr(self, 'swagger_fake_view', False):
            return Announcement.objects.none()
        
        user = self.request.user
        if not user.is_authenticated:
            return Announcement.objects.none()
        
        # Filter by tenant if available in request
        if hasattr(self.request, 'tenant') and self.request.tenant:
            return Announcement.objects.filter(tenant=self.request.tenant).order_by('-created_at')
        
        # For superusers, show all announcements
        if user.is_superuser:
            return Announcement.objects.all().order_by('-created_at')
        
        return Announcement.objects.none()
    
    def perform_create(self, serializer):
        """Set author and tenant automatically."""
        save_kwargs = {'author': self.request.user}
        
        # Set tenant from request if available
        if hasattr(self.request, 'tenant') and self.request.tenant:
            save_kwargs['tenant'] = self.request.tenant
        
        serializer.save(**save_kwargs)
        logger.info(f"Announcement created by user {self.request.user.id}")
    
    @extend_schema(
        request=None,
        responses={
            200: AnnouncementSerializer,
            400: OpenApiResponse(description="Cannot send announcement (invalid status or configuration)")
        },
        summary="Send announcement to target users"
    )
    @action(detail=True, methods=['post'], url_path='send')
    def send(self, request, pk=None):
        """
        Send the announcement to target users, creating notifications for each.
        Only DRAFT or SCHEDULED announcements can be sent.
        """
        announcement = self.get_object()
        
        # Validate announcement status
        if announcement.status not in [Announcement.Status.DRAFT, Announcement.Status.SCHEDULED]:
            return Response(
                {'error': f'Cannot send announcement with status {announcement.get_status_display()}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get target users based on target_type
        target_users = self._get_target_users(announcement)
        
        if not target_users:
            return Response(
                {'error': 'No target users found for this announcement'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create notifications for each target user
        notifications = []
        for user in target_users:
            notifications.append(Notification(
                recipient=user,
                notification_type=NotificationType.ANNOUNCEMENT,
                subject=announcement.title,
                message=announcement.message,
                status=Notification.Status.SENT,
                sent_at=timezone.now(),
                delivery_methods=['IN_APP'],
            ))
        
        # Bulk create notifications
        Notification.objects.bulk_create(notifications)
        
        # Update announcement status
        announcement.status = Announcement.Status.SENT
        announcement.sent_at = timezone.now()
        announcement.recipients_count = len(notifications)
        announcement.save(update_fields=['status', 'sent_at', 'recipients_count', 'updated_at'])
        
        logger.info(
            f"Announcement {pk} sent to {len(notifications)} users by {request.user.id}"
        )
        
        serializer = self.get_serializer(announcement)
        return Response(serializer.data)
    
    def _get_target_users(self, announcement):
        """Get the list of users to send the announcement to."""
        from apps.users.models import User
        from apps.enrollments.models import Enrollment
        
        if announcement.target_type == Announcement.TargetType.ALL_TENANT:
            # All active users in the tenant
            return User.objects.filter(
                tenant=announcement.tenant,
                is_active=True
            )
        
        elif announcement.target_type == Announcement.TargetType.COURSE_ENROLLED:
            # Users enrolled in the target course
            if not announcement.target_course:
                return User.objects.none()
            
            enrolled_user_ids = Enrollment.objects.filter(
                course=announcement.target_course,
                status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED]
            ).values_list('user_id', flat=True)
            
            return User.objects.filter(id__in=enrolled_user_ids, is_active=True)
        
        elif announcement.target_type == Announcement.TargetType.SPECIFIC_USERS:
            # Specific users by ID
            if not announcement.target_user_ids:
                return User.objects.none()
            
            return User.objects.filter(
                id__in=announcement.target_user_ids,
                tenant=announcement.tenant,
                is_active=True
            )
        
        return User.objects.none()
    
    @extend_schema(
        request=None,
        responses={200: AnnouncementSerializer},
        summary="Cancel a scheduled announcement"
    )
    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel(self, request, pk=None):
        """Cancel a scheduled or draft announcement."""
        announcement = self.get_object()
        
        if announcement.status in [Announcement.Status.SENT, Announcement.Status.CANCELLED]:
            return Response(
                {'error': f'Cannot cancel announcement with status {announcement.get_status_display()}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        announcement.status = Announcement.Status.CANCELLED
        announcement.save(update_fields=['status', 'updated_at'])
        
        logger.info(f"Announcement {pk} cancelled by {request.user.id}")
        
        serializer = self.get_serializer(announcement)
        return Response(serializer.data)
