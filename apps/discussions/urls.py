"""
URL routing for discussion forum API.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .viewsets import (
    DiscussionBookmarkViewSet,
    DiscussionReplyViewSet,
    DiscussionThreadViewSet,
)

router = DefaultRouter()
router.register(r'threads', DiscussionThreadViewSet, basename='discussion-thread')
router.register(r'replies', DiscussionReplyViewSet, basename='discussion-reply')
router.register(r'bookmarks', DiscussionBookmarkViewSet, basename='discussion-bookmark')

urlpatterns = [
    path('', include(router.urls)),
]
