from django.contrib.auth import get_user_model
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .serializers import (
    ChangePasswordSerializer,
    UserCreateSerializer,
    UserProfileSerializer,
    UserSerializer,
)

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
        tenant = self.request.tenant  # Get tenant from middleware
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
