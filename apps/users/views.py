import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .serializers import (
    ChangePasswordSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    UserCreateSerializer,
    UserProfileSerializer,
    UserSerializer,
)

logger = logging.getLogger(__name__)

User = get_user_model()


class CustomTokenObtainPairView(TokenObtainPairView):
    # You can customize the response payload here if needed
    # by overriding post method or customizing the serializer
    pass


class CustomTokenRefreshView(TokenRefreshView):
    # Potentially add custom logic if needed
    pass


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = (
        permissions.AllowAny,
    )  # Allow anyone to register (or restrict based on tenant settings?)
    serializer_class = UserCreateSerializer

    def perform_create(self, serializer):
        # In a multi-tenant system, registration might need tenant context
        # This could come from a subdomain, a signup form field, or invitation logic
        # For simplicity here, we assume tenant might be passed in request data
        # A better approach might be tenant-specific registration endpoints
        # or requiring invitation tokens.
        tenant = getattr(self.request, "tenant", None)  # Get tenant from middleware safely
        if not tenant and not serializer.validated_data.get("tenant"):
            # Allow superuser creation without tenant, maybe? Or require explicit tenant selection/detection.
            # This depends heavily on the desired registration flow.
            # For now, let's assume public registration isn't allowed and requires tenant context
            # Or modify serializer to make tenant non-required and handle default/public tenant.
            # Let's require tenant context from middleware for this example:
            if not tenant:
                from rest_framework.exceptions import PermissionDenied

                raise PermissionDenied("Registration requires a valid tenant context.")
        # Pass tenant to serializer context or directly if needed
        serializer.save(
            tenant=tenant, status=User.Status.ACTIVE
        )  # Directly activate on registration? Or send verification?


class UserProfileView(generics.RetrieveUpdateAPIView):
    """
    View to retrieve or update the profile of the currently authenticated user.
    """

    queryset = User.objects.select_related("profile").all()
    serializer_class = UserSerializer  # Use UserSerializer which includes profile
    permission_classes = (permissions.IsAuthenticated,)

    def get_object(self):
        # Return the currently authenticated user
        return self.request.user

    def perform_update(self, serializer):
        # Ensure user doesn't change their own role/status/tenant via this endpoint
        serializer.save(user=self.request.user)


class ChangePasswordView(generics.UpdateAPIView):
    """
    An endpoint for changing password.
    """

    serializer_class = ChangePasswordSerializer
    model = User
    permission_classes = (permissions.IsAuthenticated,)

    def get_object(self, queryset=None):
        return self.request.user

    def update(self, request, *args, **kwargs):
        self.object = self.get_object()
        serializer = self.get_serializer(data=request.data)

        if serializer.is_valid():
            serializer.save()
            return Response(
                {"detail": "Password updated successfully"}, status=status.HTTP_200_OK
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PasswordResetRequestView(generics.GenericAPIView):
    """
    Endpoint to request a password reset email.
    Accepts an email address and sends a reset link if the user exists.
    Always returns success to prevent email enumeration attacks.
    """

    serializer_class = PasswordResetRequestSerializer
    permission_classes = (permissions.AllowAny,)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]

        try:
            user = User.objects.get(email__iexact=email, is_active=True)
            self._send_password_reset_email(user, request)
        except User.DoesNotExist:
            # Don't reveal whether the email exists
            logger.info(f"Password reset requested for non-existent email: {email}")

        # Always return success to prevent email enumeration
        return Response(
            {"detail": "If an account exists with this email, you will receive a password reset link."},
            status=status.HTTP_200_OK,
        )

    def _send_password_reset_email(self, user, request):
        """Generate token and send password reset email."""
        # Generate password reset token
        token = default_token_generator.make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))

        # Build reset URL - frontend will handle this
        # Use FRONTEND_URL from settings if available, otherwise construct from request
        frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:3000")
        reset_url = f"{frontend_url}/reset-password?uid={uid}&token={token}"

        # Email content
        subject = "Password Reset Request"
        plain_message = f"""
Hi {user.first_name or user.email},

You requested a password reset for your account. Click the link below to reset your password:

{reset_url}

This link will expire in 24 hours.

If you did not request this password reset, please ignore this email.

Best regards,
The LMS Team
"""

        html_message = f"""
<html>
<body>
<p>Hi {user.first_name or user.email},</p>

<p>You requested a password reset for your account. Click the link below to reset your password:</p>

<p><a href="{reset_url}">Reset Your Password</a></p>

<p>Or copy and paste this URL into your browser:</p>
<p>{reset_url}</p>

<p>This link will expire in 24 hours.</p>

<p>If you did not request this password reset, please ignore this email.</p>

<p>Best regards,<br>The LMS Team</p>
</body>
</html>
"""

        try:
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=False,
            )
            logger.info(f"Password reset email sent to {user.email}")
        except Exception as e:
            logger.error(f"Failed to send password reset email to {user.email}: {e}")
            # Don't raise - we don't want to reveal email existence


class PasswordResetConfirmView(generics.GenericAPIView):
    """
    Endpoint to confirm a password reset with the token and set a new password.
    """

    serializer_class = PasswordResetConfirmSerializer
    permission_classes = (permissions.AllowAny,)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            {"detail": "Password has been reset successfully."},
            status=status.HTTP_200_OK,
        )
