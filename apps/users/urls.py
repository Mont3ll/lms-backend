from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import (  # CustomTokenObtainPairView, # Use if customized; CustomTokenRefreshView,  # Use if customized
    ChangePasswordView,
    RegisterView,
    UserProfileView,
)

app_name = "users_auth"

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path(
        "login/", TokenObtainPairView.as_view(), name="token_obtain_pair"
    ),  # Standard login
    path(
        "login/refresh/", TokenRefreshView.as_view(), name="token_refresh"
    ),  # Standard refresh
    # path('login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'), # Use custom view if needed
    # path('login/refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'), # Use custom view if needed
    path("profile/", UserProfileView.as_view(), name="user_profile"),
    path(
        "profile/change-password/", ChangePasswordView.as_view(), name="change_password"
    ),
    # Add URLs for password reset, email verification etc. if using libraries like dj-rest-auth or implementing manually
    # path('password/reset/', ...),
    # path('password/reset/confirm/', ...),
    # path('email/verify/', ...),
]
