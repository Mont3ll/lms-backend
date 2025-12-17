"""
ViewSets for discussion forum API.

Provides CRUD operations for discussion threads and replies,
plus actions for liking, bookmarking, and marking views.
"""

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

from apps.enrollments.models import Enrollment

from .models import (
    DiscussionBookmark,
    DiscussionLike,
    DiscussionReply,
    DiscussionThread,
    DiscussionView,
)
from .serializers import (
    DiscussionBookmarkSerializer,
    DiscussionReplyCreateSerializer,
    DiscussionReplySerializer,
    DiscussionThreadCreateSerializer,
    DiscussionThreadListSerializer,
    DiscussionThreadSerializer,
)


class IsEnrolledInCourse(permissions.BasePermission):
    """
    Permission check for course enrollment.
    
    Users must be enrolled in the course, or be an instructor/admin,
    to participate in discussions.
    """
    
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        
        # Admins and staff can access all discussions
        if request.user.is_staff or request.user.is_superuser:
            return True
        
        # For list views, we filter by enrollment in get_queryset
        return True
    
    def has_object_permission(self, request, view, obj):
        user = request.user
        
        # Admins and staff can access all
        if user.is_staff or user.is_superuser:
            return True
        
        # Get the course from the object
        if isinstance(obj, DiscussionThread):
            course = obj.course
        elif isinstance(obj, DiscussionReply):
            course = obj.thread.course
        else:
            return False
        
        # Course instructor can access
        if course.instructor == user:
            return True
        
        # Check if user is enrolled in the course
        return Enrollment.objects.filter(
            user=user,
            course=course,
            status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED]
        ).exists()


@extend_schema(tags=['Discussions'])
class DiscussionThreadViewSet(viewsets.ModelViewSet):
    """
    ViewSet for discussion threads.
    
    Provides:
    - List threads for a course (filtered by course_id query param)
    - Create new threads
    - Update own threads (or any thread for instructors/admins)
    - Delete own threads (or any thread for instructors/admins)
    - Like/unlike a thread
    - Bookmark/unbookmark a thread
    - Mark thread as viewed
    """
    
    permission_classes = [permissions.IsAuthenticated, IsEnrolledInCourse]
    
    def get_serializer_class(self):
        if self.action == 'create':
            return DiscussionThreadCreateSerializer
        if self.action == 'list':
            return DiscussionThreadListSerializer
        return DiscussionThreadSerializer
    
    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return DiscussionThread.objects.none()
        
        user = self.request.user
        tenant = getattr(self.request, 'tenant', None)
        
        # Base queryset with tenant filter
        queryset = DiscussionThread.objects.all()
        if tenant:
            queryset = queryset.filter(tenant=tenant)
        
        # Filter by course if specified
        course_id = self.request.query_params.get('course_id')
        if course_id:
            queryset = queryset.filter(course_id=course_id)
        
        # Filter by content_item if specified
        content_item_id = self.request.query_params.get('content_item_id')
        if content_item_id:
            queryset = queryset.filter(content_item_id=content_item_id)
        
        # For non-admin users, only show threads from courses they're enrolled in
        if not user.is_staff and not user.is_superuser:
            enrolled_course_ids = Enrollment.objects.filter(
                user=user,
                status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED]
            ).values_list('course_id', flat=True)
            
            # Also include courses where user is instructor
            from apps.courses.models import Course
            instructor_course_ids = Course.objects.filter(
                instructor=user
            ).values_list('id', flat=True)
            
            allowed_course_ids = set(enrolled_course_ids) | set(instructor_course_ids)
            queryset = queryset.filter(course_id__in=allowed_course_ids)
        
        # Filter out archived threads unless explicitly requested
        include_archived = self.request.query_params.get('include_archived', 'false').lower() == 'true'
        if not include_archived:
            queryset = queryset.exclude(status=DiscussionThread.Status.ARCHIVED)
        
        return queryset.select_related('author', 'course', 'content_item').prefetch_related('replies')
    
    @extend_schema(
        parameters=[
            OpenApiParameter(name='course_id', description='Filter by Course UUID', required=False, type=OpenApiTypes.UUID),
            OpenApiParameter(name='content_item_id', description='Filter by Content Item UUID', required=False, type=OpenApiTypes.UUID),
            OpenApiParameter(name='include_archived', description='Include archived threads', required=False, type=OpenApiTypes.BOOL),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
    
    def perform_create(self, serializer):
        """Set author and tenant when creating a thread."""
        tenant = getattr(self.request, 'tenant', None)
        serializer.save(author=self.request.user, tenant=tenant)
    
    def perform_update(self, serializer):
        """Only allow authors, instructors, and admins to update threads."""
        thread = self.get_object()
        user = self.request.user
        
        # Check if user can update
        is_author = thread.author == user
        is_instructor = thread.course.instructor == user
        is_admin = user.is_staff or user.is_superuser
        
        if not (is_author or is_instructor or is_admin):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You don't have permission to update this thread.")
        
        serializer.save()
    
    def perform_destroy(self, instance):
        """Only allow authors, instructors, and admins to delete threads."""
        user = self.request.user
        
        is_author = instance.author == user
        is_instructor = instance.course.instructor == user
        is_admin = user.is_staff or user.is_superuser
        
        if not (is_author or is_instructor or is_admin):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You don't have permission to delete this thread.")
        
        instance.delete()
    
    @extend_schema(
        description="Toggle like on a discussion thread",
        responses={200: OpenApiResponse(description="Like toggled successfully")}
    )
    @action(detail=True, methods=['post'], url_path='like')
    def toggle_like(self, request, pk=None):
        """Toggle like on a thread."""
        thread = self.get_object()
        user = request.user
        
        like, created = DiscussionLike.objects.get_or_create(
            user=user,
            thread=thread,
            defaults={'reply': None}
        )
        
        if not created:
            like.delete()
            thread.like_count = max(0, thread.like_count - 1)
            thread.save(update_fields=['like_count'])
            return Response({'liked': False, 'like_count': thread.like_count})
        
        thread.like_count += 1
        thread.save(update_fields=['like_count'])
        return Response({'liked': True, 'like_count': thread.like_count})
    
    @extend_schema(
        description="Toggle bookmark on a discussion thread",
        responses={200: OpenApiResponse(description="Bookmark toggled successfully")}
    )
    @action(detail=True, methods=['post'], url_path='bookmark')
    def toggle_bookmark(self, request, pk=None):
        """Toggle bookmark on a thread."""
        thread = self.get_object()
        user = request.user
        
        bookmark, created = DiscussionBookmark.objects.get_or_create(
            user=user,
            thread=thread
        )
        
        if not created:
            bookmark.delete()
            return Response({'bookmarked': False})
        
        return Response({'bookmarked': True})
    
    @extend_schema(
        description="Mark thread as viewed (updates last viewed timestamp)",
        responses={200: OpenApiResponse(description="Thread marked as viewed")}
    )
    @action(detail=True, methods=['post'], url_path='view')
    def mark_viewed(self, request, pk=None):
        """Mark thread as viewed by current user."""
        thread = self.get_object()
        user = request.user
        
        view, created = DiscussionView.objects.update_or_create(
            user=user,
            thread=thread,
            defaults={'last_viewed_at': timezone.now()}
        )
        
        # Increment view count only on first view
        if created:
            thread.view_count += 1
            thread.save(update_fields=['view_count'])
        
        return Response({
            'viewed': True,
            'view_count': thread.view_count,
            'last_viewed_at': view.last_viewed_at
        })
    
    @extend_schema(
        description="Pin or unpin a thread (instructors/admins only)",
        responses={200: OpenApiResponse(description="Thread pin status toggled")}
    )
    @action(detail=True, methods=['post'], url_path='pin')
    def toggle_pin(self, request, pk=None):
        """Toggle pin status on a thread (instructors/admins only)."""
        thread = self.get_object()
        user = request.user
        
        # Only instructors and admins can pin
        is_instructor = thread.course.instructor == user
        is_admin = user.is_staff or user.is_superuser
        
        if not (is_instructor or is_admin):
            return Response(
                {'detail': 'Only instructors and admins can pin threads.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        thread.is_pinned = not thread.is_pinned
        thread.save(update_fields=['is_pinned'])
        
        return Response({'is_pinned': thread.is_pinned})
    
    @extend_schema(
        description="Lock or unlock a thread (instructors/admins only)",
        responses={200: OpenApiResponse(description="Thread lock status toggled")}
    )
    @action(detail=True, methods=['post'], url_path='lock')
    def toggle_lock(self, request, pk=None):
        """Toggle lock status on a thread (instructors/admins only)."""
        thread = self.get_object()
        user = request.user
        
        # Only instructors and admins can lock
        is_instructor = thread.course.instructor == user
        is_admin = user.is_staff or user.is_superuser
        
        if not (is_instructor or is_admin):
            return Response(
                {'detail': 'Only instructors and admins can lock threads.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if thread.status == DiscussionThread.Status.LOCKED:
            thread.status = DiscussionThread.Status.ACTIVE
        else:
            thread.status = DiscussionThread.Status.LOCKED
        
        thread.save(update_fields=['status'])
        
        return Response({'status': thread.status})


@extend_schema(tags=['Discussions'])
class DiscussionReplyViewSet(viewsets.ModelViewSet):
    """
    ViewSet for discussion replies.
    
    Provides:
    - List replies for a thread (filtered by thread_id query param)
    - Create new replies
    - Update own replies (or any reply for instructors/admins)
    - Delete own replies (or any reply for instructors/admins)
    - Like/unlike a reply
    """
    
    permission_classes = [permissions.IsAuthenticated, IsEnrolledInCourse]
    
    def get_serializer_class(self):
        if self.action == 'create':
            return DiscussionReplyCreateSerializer
        return DiscussionReplySerializer
    
    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return DiscussionReply.objects.none()
        
        user = self.request.user
        tenant = getattr(self.request, 'tenant', None)
        
        # Base queryset
        queryset = DiscussionReply.objects.all()
        if tenant:
            queryset = queryset.filter(thread__tenant=tenant)
        
        # Filter by thread if specified
        thread_id = self.request.query_params.get('thread_id')
        if thread_id:
            queryset = queryset.filter(thread_id=thread_id)
        
        # For non-admin users, only show replies from courses they're enrolled in
        if not user.is_staff and not user.is_superuser:
            enrolled_course_ids = Enrollment.objects.filter(
                user=user,
                status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED]
            ).values_list('course_id', flat=True)
            
            from apps.courses.models import Course
            instructor_course_ids = Course.objects.filter(
                instructor=user
            ).values_list('id', flat=True)
            
            allowed_course_ids = set(enrolled_course_ids) | set(instructor_course_ids)
            queryset = queryset.filter(thread__course_id__in=allowed_course_ids)
        
        # Only show non-hidden replies (unless admin or author)
        if not user.is_staff and not user.is_superuser:
            queryset = queryset.filter(
                Q(is_hidden=False) | Q(author=user)
            )
        
        return queryset.select_related('author', 'thread', 'parent_reply')
    
    @extend_schema(
        parameters=[
            OpenApiParameter(name='thread_id', description='Filter by Thread UUID', required=False, type=OpenApiTypes.UUID),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
    
    def perform_create(self, serializer):
        """Set author when creating a reply and update thread counts."""
        thread = serializer.validated_data['thread']
        
        # Check if thread is locked
        if thread.status == DiscussionThread.Status.LOCKED:
            from rest_framework.exceptions import ValidationError
            raise ValidationError("This thread is locked and cannot receive new replies.")
        
        reply = serializer.save(author=self.request.user)
        
        # Update thread reply count and last activity
        thread.reply_count += 1
        thread.last_activity_at = timezone.now()
        thread.save(update_fields=['reply_count', 'last_activity_at'])
    
    def perform_update(self, serializer):
        """Only allow authors, instructors, and admins to update replies."""
        reply = self.get_object()
        user = self.request.user
        
        is_author = reply.author == user
        is_instructor = reply.thread.course.instructor == user
        is_admin = user.is_staff or user.is_superuser
        
        if not (is_author or is_instructor or is_admin):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You don't have permission to update this reply.")
        
        # Mark as edited
        serializer.save(is_edited=True, edited_at=timezone.now())
    
    def perform_destroy(self, instance):
        """Only allow authors, instructors, and admins to delete replies."""
        user = self.request.user
        
        is_author = instance.author == user
        is_instructor = instance.thread.course.instructor == user
        is_admin = user.is_staff or user.is_superuser
        
        if not (is_author or is_instructor or is_admin):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You don't have permission to delete this reply.")
        
        thread = instance.thread
        instance.delete()
        
        # Update thread reply count
        thread.reply_count = max(0, thread.reply_count - 1)
        thread.save(update_fields=['reply_count'])
    
    @extend_schema(
        description="Toggle like on a discussion reply",
        responses={200: OpenApiResponse(description="Like toggled successfully")}
    )
    @action(detail=True, methods=['post'], url_path='like')
    def toggle_like(self, request, pk=None):
        """Toggle like on a reply."""
        reply = self.get_object()
        user = request.user
        
        like, created = DiscussionLike.objects.get_or_create(
            user=user,
            reply=reply,
            defaults={'thread': None}
        )
        
        if not created:
            like.delete()
            reply.like_count = max(0, reply.like_count - 1)
            reply.save(update_fields=['like_count'])
            return Response({'liked': False, 'like_count': reply.like_count})
        
        reply.like_count += 1
        reply.save(update_fields=['like_count'])
        return Response({'liked': True, 'like_count': reply.like_count})
    
    @extend_schema(
        description="Hide or unhide a reply (instructors/admins only)",
        request={'application/json': {'type': 'object', 'properties': {'reason': {'type': 'string'}}}},
        responses={200: OpenApiResponse(description="Reply visibility toggled")}
    )
    @action(detail=True, methods=['post'], url_path='hide')
    def toggle_hide(self, request, pk=None):
        """Toggle hide status on a reply (instructors/admins only)."""
        reply = self.get_object()
        user = request.user
        
        is_instructor = reply.thread.course.instructor == user
        is_admin = user.is_staff or user.is_superuser
        
        if not (is_instructor or is_admin):
            return Response(
                {'detail': 'Only instructors and admins can hide replies.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        reply.is_hidden = not reply.is_hidden
        if reply.is_hidden:
            reply.hidden_reason = request.data.get('reason', '')
        else:
            reply.hidden_reason = ''
        
        reply.save(update_fields=['is_hidden', 'hidden_reason'])
        
        return Response({
            'is_hidden': reply.is_hidden,
            'hidden_reason': reply.hidden_reason
        })


@extend_schema(tags=['Discussions'])
class DiscussionBookmarkViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for user's bookmarked threads.
    
    Read-only - bookmarks are created/deleted via the thread toggle_bookmark action.
    """
    
    serializer_class = DiscussionBookmarkSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return DiscussionBookmark.objects.none()
        
        return DiscussionBookmark.objects.filter(
            user=self.request.user
        ).select_related('thread', 'thread__author', 'thread__course')
