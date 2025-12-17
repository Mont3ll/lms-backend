"""
Serializers for discussion forum API.
"""

from rest_framework import serializers

from apps.users.serializers import UserBasicSerializer

from .models import (
    DiscussionBookmark,
    DiscussionLike,
    DiscussionReply,
    DiscussionThread,
    DiscussionView,
)


class DiscussionReplySerializer(serializers.ModelSerializer):
    """Serializer for discussion replies."""
    
    author = UserBasicSerializer(read_only=True)
    is_liked = serializers.SerializerMethodField()
    child_replies = serializers.SerializerMethodField()
    
    class Meta:
        model = DiscussionReply
        fields = [
            'id',
            'thread',
            'author',
            'parent_reply',
            'content',
            'is_hidden',
            'like_count',
            'is_edited',
            'edited_at',
            'is_liked',
            'child_replies',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'author',
            'is_hidden',
            'like_count',
            'is_edited',
            'edited_at',
            'created_at',
            'updated_at',
        ]
    
    def get_is_liked(self, obj) -> bool:
        """Check if current user has liked this reply."""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return DiscussionLike.objects.filter(
                user=request.user,
                reply=obj
            ).exists()
        return False
    
    def get_child_replies(self, obj):
        """Get nested replies (one level deep)."""
        # Only include child replies for top-level replies
        if obj.parent_reply is None:
            children = obj.child_replies.filter(is_hidden=False)[:5]
            return DiscussionReplySerializer(
                children, 
                many=True, 
                context=self.context
            ).data
        return []


class DiscussionReplyCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating discussion replies."""
    
    class Meta:
        model = DiscussionReply
        fields = ['thread', 'parent_reply', 'content']
    
    def validate_parent_reply(self, value):
        """Ensure parent reply belongs to the same thread."""
        if value:
            thread = self.initial_data.get('thread')
            if str(value.thread_id) != str(thread):
                raise serializers.ValidationError(
                    "Parent reply must belong to the same thread."
                )
        return value


class DiscussionThreadSerializer(serializers.ModelSerializer):
    """Serializer for discussion threads."""
    
    author = UserBasicSerializer(read_only=True)
    is_liked = serializers.SerializerMethodField()
    is_bookmarked = serializers.SerializerMethodField()
    has_new_replies = serializers.SerializerMethodField()
    recent_replies = serializers.SerializerMethodField()
    
    class Meta:
        model = DiscussionThread
        fields = [
            'id',
            'course',
            'content_item',
            'author',
            'title',
            'content',
            'status',
            'is_pinned',
            'is_announcement',
            'reply_count',
            'like_count',
            'view_count',
            'is_liked',
            'is_bookmarked',
            'has_new_replies',
            'recent_replies',
            'last_activity_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'author',
            'status',
            'is_pinned',
            'is_announcement',
            'reply_count',
            'like_count',
            'view_count',
            'last_activity_at',
            'created_at',
            'updated_at',
        ]
    
    def get_is_liked(self, obj) -> bool:
        """Check if current user has liked this thread."""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return DiscussionLike.objects.filter(
                user=request.user,
                thread=obj
            ).exists()
        return False
    
    def get_is_bookmarked(self, obj) -> bool:
        """Check if current user has bookmarked this thread."""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return DiscussionBookmark.objects.filter(
                user=request.user,
                thread=obj
            ).exists()
        return False
    
    def get_has_new_replies(self, obj) -> bool:
        """Check if thread has new replies since user's last view."""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            view = DiscussionView.objects.filter(
                user=request.user,
                thread=obj
            ).first()
            if view:
                return obj.last_activity_at > view.last_viewed_at
            return True  # Never viewed = has new content
        return False
    
    def get_recent_replies(self, obj):
        """Get first few replies for preview."""
        replies = obj.replies.filter(
            is_hidden=False,
            parent_reply__isnull=True
        )[:3]
        return DiscussionReplySerializer(
            replies,
            many=True,
            context=self.context
        ).data


class DiscussionThreadCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating discussion threads."""
    
    class Meta:
        model = DiscussionThread
        fields = ['course', 'content_item', 'title', 'content']
    
    def validate_content_item(self, value):
        """Ensure content item belongs to the course."""
        if value:
            course = self.initial_data.get('course')
            if str(value.module.course_id) != str(course):
                raise serializers.ValidationError(
                    "Content item must belong to the selected course."
                )
        return value


class DiscussionThreadListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for thread lists."""
    
    author = UserBasicSerializer(read_only=True)
    is_bookmarked = serializers.SerializerMethodField()
    has_new_replies = serializers.SerializerMethodField()
    
    class Meta:
        model = DiscussionThread
        fields = [
            'id',
            'course',
            'content_item',
            'author',
            'title',
            'status',
            'is_pinned',
            'is_announcement',
            'reply_count',
            'like_count',
            'view_count',
            'is_bookmarked',
            'has_new_replies',
            'last_activity_at',
            'created_at',
        ]
    
    def get_is_bookmarked(self, obj) -> bool:
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return DiscussionBookmark.objects.filter(
                user=request.user,
                thread=obj
            ).exists()
        return False
    
    def get_has_new_replies(self, obj) -> bool:
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            view = DiscussionView.objects.filter(
                user=request.user,
                thread=obj
            ).first()
            if view:
                return obj.last_activity_at > view.last_viewed_at
            return True
        return False


class DiscussionBookmarkSerializer(serializers.ModelSerializer):
    """Serializer for bookmarks."""
    
    thread = DiscussionThreadListSerializer(read_only=True)
    
    class Meta:
        model = DiscussionBookmark
        fields = ['id', 'thread', 'created_at']
        read_only_fields = ['id', 'thread', 'created_at']
