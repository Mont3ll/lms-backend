from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import (  # CustomTokenObtainPairView, # Use if customized; CustomTokenRefreshView,  # Use if customized
    ChangePasswordView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
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
    # Password Reset URLs
    path(
        "password/reset/",
        PasswordResetRequestView.as_view(),
        name="password_reset_request",
    ),
    path(
        "password/reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
]
