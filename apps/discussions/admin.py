"""
Admin configuration for discussion forum models.
"""

from django.contrib import admin

from .models import (
    DiscussionBookmark,
    DiscussionLike,
    DiscussionReply,
    DiscussionThread,
    DiscussionView,
)


@admin.register(DiscussionThread)
class DiscussionThreadAdmin(admin.ModelAdmin):
    """Admin for discussion threads."""
    
    list_display = [
        'title',
        'course',
        'author',
        'status',
        'is_pinned',
        'is_announcement',
        'reply_count',
        'like_count',
        'view_count',
        'created_at',
    ]
    list_filter = [
        'status',
        'is_pinned',
        'is_announcement',
        'tenant',
        'created_at',
    ]
    search_fields = [
        'title',
        'content',
        'author__email',
        'author__first_name',
        'author__last_name',
        'course__title',
    ]
    readonly_fields = [
        'reply_count',
        'like_count',
        'view_count',
        'last_activity_at',
        'created_at',
        'updated_at',
    ]
    autocomplete_fields = ['course', 'author', 'content_item']
    ordering = ['-created_at']


@admin.register(DiscussionReply)
class DiscussionReplyAdmin(admin.ModelAdmin):
    """Admin for discussion replies."""
    
    list_display = [
        'get_thread_title',
        'author',
        'like_count',
        'is_hidden',
        'is_edited',
        'created_at',
    ]
    list_filter = [
        'is_hidden',
        'is_edited',
        'created_at',
    ]
    search_fields = [
        'content',
        'author__email',
        'thread__title',
    ]
    readonly_fields = [
        'like_count',
        'is_edited',
        'edited_at',
        'created_at',
        'updated_at',
    ]
    autocomplete_fields = ['thread', 'author', 'parent_reply']
    ordering = ['-created_at']
    
    @admin.display(description='Thread')
    def get_thread_title(self, obj):
        return obj.thread.title


@admin.register(DiscussionLike)
class DiscussionLikeAdmin(admin.ModelAdmin):
    """Admin for discussion likes."""
    
    list_display = [
        'user',
        'get_target',
        'created_at',
    ]
    list_filter = ['created_at']
    search_fields = [
        'user__email',
        'thread__title',
        'reply__content',
    ]
    autocomplete_fields = ['user', 'thread', 'reply']
    ordering = ['-created_at']
    
    @admin.display(description='Target')
    def get_target(self, obj):
        if obj.thread:
            return f"Thread: {obj.thread.title}"
        elif obj.reply:
            return f"Reply on: {obj.reply.thread.title}"
        return "N/A"


@admin.register(DiscussionBookmark)
class DiscussionBookmarkAdmin(admin.ModelAdmin):
    """Admin for discussion bookmarks."""
    
    list_display = [
        'user',
        'get_thread_title',
        'created_at',
    ]
    list_filter = ['created_at']
    search_fields = [
        'user__email',
        'thread__title',
    ]
    autocomplete_fields = ['user', 'thread']
    ordering = ['-created_at']
    
    @admin.display(description='Thread')
    def get_thread_title(self, obj):
        return obj.thread.title


@admin.register(DiscussionView)
class DiscussionViewAdmin(admin.ModelAdmin):
    """Admin for discussion views."""
    
    list_display = [
        'user',
        'get_thread_title',
        'last_viewed_at',
    ]
    list_filter = ['last_viewed_at']
    search_fields = [
        'user__email',
        'thread__title',
    ]
    autocomplete_fields = ['user', 'thread']
    ordering = ['-last_viewed_at']
    
    @admin.display(description='Thread')
    def get_thread_title(self, obj):
        return obj.thread.title
