"""
Discussion forum models for social learning.

Provides course-level discussion threads with replies, likes, and bookmarks.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import TimestampedModel
from apps.users.models import User


class DiscussionThread(TimestampedModel):
    """
    A discussion thread within a course.
    
    Can be pinned by instructors, locked to prevent new replies,
    and associated with specific course content.
    """
    
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", _("Active")
        LOCKED = "LOCKED", _("Locked")
        ARCHIVED = "ARCHIVED", _("Archived")
    
    tenant = models.ForeignKey(
        'core.Tenant',
        on_delete=models.CASCADE,
        related_name='discussion_threads'
    )
    course = models.ForeignKey(
        'courses.Course',
        on_delete=models.CASCADE,
        related_name='discussion_threads'
    )
    # Optional: Link to specific content item for context-specific discussions
    content_item = models.ForeignKey(
        'courses.ContentItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='discussion_threads',
        help_text="Optional: Link to specific content for contextual discussions"
    )
    
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='discussion_threads'
    )
    
    title = models.CharField(max_length=255)
    content = models.TextField(help_text="Thread content (supports markdown)")
    
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True
    )
    is_pinned = models.BooleanField(
        default=False,
        help_text="Pinned threads appear at top of list"
    )
    is_announcement = models.BooleanField(
        default=False,
        help_text="Announcement threads are highlighted"
    )
    
    # Cached counts for performance
    reply_count = models.PositiveIntegerField(default=0)
    like_count = models.PositiveIntegerField(default=0)
    view_count = models.PositiveIntegerField(default=0)
    
    last_activity_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.title} - {self.course.title}"
    
    class Meta:
        ordering = ['-is_pinned', '-last_activity_at']
        indexes = [
            models.Index(fields=['course', 'status']),
            models.Index(fields=['author', 'created_at']),
            models.Index(fields=['content_item']),
        ]


class DiscussionReply(TimestampedModel):
    """
    A reply to a discussion thread or another reply.
    
    Supports nested replies (parent_reply) for threaded conversations.
    """
    
    thread = models.ForeignKey(
        DiscussionThread,
        on_delete=models.CASCADE,
        related_name='replies'
    )
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='discussion_replies'
    )
    # Support nested replies
    parent_reply = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='child_replies',
        help_text="Parent reply for nested threading"
    )
    
    content = models.TextField(help_text="Reply content (supports markdown)")
    
    # Moderation
    is_hidden = models.BooleanField(
        default=False,
        help_text="Hidden replies are only visible to moderators"
    )
    hidden_reason = models.CharField(max_length=255, blank=True)
    
    # Cached counts
    like_count = models.PositiveIntegerField(default=0)
    
    # Edited tracking
    is_edited = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"Reply by {self.author.get_full_name()} on {self.thread.title}"
    
    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['thread', 'created_at']),
            models.Index(fields=['author', 'created_at']),
            models.Index(fields=['parent_reply']),
        ]


class DiscussionLike(TimestampedModel):
    """
    A like/upvote on a thread or reply.
    
    Uses generic approach - can like either threads or replies.
    """
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='discussion_likes'
    )
    # Like can be on thread or reply (one must be set)
    thread = models.ForeignKey(
        DiscussionThread,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='likes'
    )
    reply = models.ForeignKey(
        DiscussionReply,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='likes'
    )
    
    class Meta:
        constraints = [
            # Ensure at least one of thread or reply is set
            models.CheckConstraint(
                check=(
                    models.Q(thread__isnull=False, reply__isnull=True) |
                    models.Q(thread__isnull=True, reply__isnull=False)
                ),
                name='like_thread_or_reply_not_both'
            ),
            # Unique like per user per thread
            models.UniqueConstraint(
                fields=['user', 'thread'],
                condition=models.Q(thread__isnull=False),
                name='unique_user_thread_like'
            ),
            # Unique like per user per reply
            models.UniqueConstraint(
                fields=['user', 'reply'],
                condition=models.Q(reply__isnull=False),
                name='unique_user_reply_like'
            ),
        ]


class DiscussionBookmark(TimestampedModel):
    """
    A bookmark to save a thread for later reference.
    """
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='discussion_bookmarks'
    )
    thread = models.ForeignKey(
        DiscussionThread,
        on_delete=models.CASCADE,
        related_name='bookmarks'
    )
    
    class Meta:
        unique_together = ['user', 'thread']
        ordering = ['-created_at']


class DiscussionView(TimestampedModel):
    """
    Tracks thread views for analytics and "new replies" indicators.
    """
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='discussion_views'
    )
    thread = models.ForeignKey(
        DiscussionThread,
        on_delete=models.CASCADE,
        related_name='views'
    )
    last_viewed_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['user', 'thread']
