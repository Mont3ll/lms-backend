from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import UserProfile, LearnerGroup, GroupMembership, Tenant # Import Tenant if needed for validation

User = get_user_model()


class UserBasicSerializer(serializers.ModelSerializer):
    """Lightweight user serializer for nested representations."""
    
    full_name = serializers.CharField(read_only=True)
    avatar_url = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ('id', 'email', 'first_name', 'last_name', 'full_name', 'role', 'avatar_url')
        read_only_fields = fields
    
    def get_avatar_url(self, obj) -> str | None:
        """Get avatar URL from user profile if available."""
        if hasattr(obj, 'profile') and obj.profile and obj.profile.avatar:
            return obj.profile.avatar.url
        return None


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ('id', 'avatar', 'bio', 'language', 'timezone', 'preferences', 'updated_at')
        read_only_fields = ('id', 'updated_at')

class UserSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(required=False, allow_null=True) # Allow null profile initially
    # REMOVED redundant source='full_name'
    full_name = serializers.CharField(read_only=True) # Property defined on User model
    tenant_slug = serializers.CharField(source='tenant.slug', read_only=True, allow_null=True)

    class Meta:
        model = User
        fields = (
            'id', 'email', 'first_name', 'last_name', 'full_name',
            'role', 'status', 'profile', 'tenant', 'tenant_slug',
            'is_active', 'is_staff', 'last_login', 'date_joined'
        )
        read_only_fields = (
            'id', 'is_active', 'is_staff', 'last_login', 'date_joined', 'tenant', 'tenant_slug', 'email' # Make email read-only after creation
        )
        extra_kwargs = {
            # Removed email from here as it's now read_only
            'first_name': {'required': True, 'allow_blank': False},
            'last_name': {'required': True, 'allow_blank': False},
            'role': {'required': False},
            'status': {'required': False},
            'profile': {'required': False, 'allow_null': True},
        }

    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile', None)
        # Prevent changing email, tenant, role, status directly via this serializer update?
        # Admins should use specific endpoints/serializers.
        validated_data.pop('email', None)
        validated_data.pop('tenant', None)
        validated_data.pop('role', None)
        validated_data.pop('status', None)

        instance = super().update(instance, validated_data)

        # Handle nested profile update
        if profile_data is not None:
            profile = instance.profile
            # If profile doesn't exist (e.g., old user), create it
            if profile is None:
                profile = UserProfile.objects.create(user=instance, **profile_data)
            else:
                profile_serializer = UserProfileSerializer(profile, data=profile_data, partial=True)
                if profile_serializer.is_valid(raise_exception=True):
                    profile_serializer.save()
        return instance

class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})
    password2 = serializers.CharField(write_only=True, required=True, label="Confirm password", style={'input_type': 'password'})
    # Make tenant writable for admin creation, but ensure validation in view
    tenant = serializers.PrimaryKeyRelatedField(queryset=Tenant.objects.all(), required=True, allow_null=False)

    class Meta:
        model = User
        fields = ('email', 'first_name', 'last_name', 'password', 'password2', 'role', 'tenant', 'status')
        extra_kwargs = {
            'first_name': {'required': True},
            'last_name': {'required': True},
            'role': {'required': False}, # Default is LEARNER
            'status': {'required': False}, # Default is INVITED? Or ACTIVE? Let's use model default (INVITED)
            # tenant handled by PrimaryKeyRelatedField
        }

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with that email already exists.")
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({"password2": "Password fields didn't match."})

        # Use a temporary user instance for password validation if needed
        temp_user_data = {k: v for k, v in attrs.items() if k not in ['password', 'password2', 'tenant']}
        temp_user = User(**temp_user_data)
        try:
            validate_password(attrs['password'], user=temp_user)
        except DjangoValidationError as e:
            raise serializers.ValidationError({'password': list(e.messages)})

        return attrs

    def create(self, validated_data):
        validated_data.pop('password2')
        # create_user handles password hashing and saving
        user = User.objects.create_user(**validated_data)
        return user


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True, write_only=True, style={'input_type': 'password'})
    new_password = serializers.CharField(required=True, write_only=True, style={'input_type': 'password'})
    new_password2 = serializers.CharField(required=True, write_only=True, label="Confirm new password", style={'input_type': 'password'})

    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Your old password was entered incorrectly. Please enter it again.")
        return value

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password2']:
            raise serializers.ValidationError({"new_password2": "Password fields didn't match."})
        try:
            validate_password(attrs['new_password'], user=self.context['request'].user)
        except DjangoValidationError as e:
            raise serializers.ValidationError({'new_password': list(e.messages)})
        return attrs

    def save(self, **kwargs):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save(update_fields=['password', 'updated_at']) # Only update password and timestamp
        return user

# --- Password Reset Serializers ---

class PasswordResetRequestSerializer(serializers.Serializer):
    """Serializer for requesting a password reset."""
    email = serializers.EmailField(required=True)

    def validate_email(self, value):
        """Normalize the email and check if a user exists."""
        # Always return success to prevent email enumeration attacks
        # The actual check happens in the view
        return value.lower()


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Serializer for confirming a password reset."""
    uid = serializers.CharField(required=True)
    token = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, write_only=True, style={'input_type': 'password'})
    new_password2 = serializers.CharField(required=True, write_only=True, label="Confirm new password", style={'input_type': 'password'})

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password2']:
            raise serializers.ValidationError({"new_password2": "Password fields didn't match."})

        # Decode uid and get user
        from django.utils.http import urlsafe_base64_decode
        from django.contrib.auth.tokens import default_token_generator

        try:
            uid = urlsafe_base64_decode(attrs['uid']).decode()
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise serializers.ValidationError({"uid": "Invalid reset link."})

        # Verify token
        if not default_token_generator.check_token(user, attrs['token']):
            raise serializers.ValidationError({"token": "Invalid or expired reset link."})

        # Validate password strength
        try:
            validate_password(attrs['new_password'], user=user)
        except DjangoValidationError as e:
            raise serializers.ValidationError({'new_password': list(e.messages)})

        attrs['user'] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data['user']
        user.set_password(self.validated_data['new_password'])
        user.save(update_fields=['password', 'updated_at'])
        return user


# --- Learner Group Serializers ---

class GroupMembershipSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_id = serializers.UUIDField(source='user.id', required=False) # Writable for adding members

    class Meta:
        model = GroupMembership
        fields = ('id', 'user_id', 'user_email', 'group', 'date_joined')
        read_only_fields = ('id', 'user_email', 'date_joined')
        extra_kwargs = {
            'group': {'write_only': True, 'required': False}
        }


class LearnerGroupSerializer(serializers.ModelSerializer):
    members = GroupMembershipSerializer(source='memberships', many=True, read_only=True)
    member_count = serializers.IntegerField(source='members.count', read_only=True)
    member_ids = serializers.ListField(
        child=serializers.UUIDField(), write_only=True, required=False
    )
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)

    class Meta:
        model = LearnerGroup
        fields = ('id', 'name', 'description', 'tenant', 'tenant_name', 'members', 'member_count', 'member_ids', 'created_at', 'updated_at')
        read_only_fields = ('id', 'tenant', 'tenant_name', 'members', 'member_count', 'created_at', 'updated_at')

    def validate_member_ids(self, member_ids):
        """Ensure provided member IDs exist and belong to the correct tenant."""
        tenant = self.context['request'].tenant
        if not tenant:
             # This check might be redundant if view permissions are correct
             raise serializers.ValidationError("Tenant context unavailable for validation.")
        if member_ids:
             valid_users_count = User.objects.filter(id__in=member_ids, tenant=tenant).count()
             if valid_users_count != len(member_ids):
                 raise serializers.ValidationError("One or more user IDs are invalid or do not belong to this tenant.")
        return member_ids

    def create(self, validated_data):
        member_ids = validated_data.pop('member_ids', [])
        tenant = self.context['request'].tenant
        if not tenant:
             raise serializers.ValidationError("Tenant context is required to create a group.")
        validated_data['tenant'] = tenant
        group = LearnerGroup.objects.create(**validated_data)
        if member_ids:
            # Validation done in validate_member_ids
            memberships = [GroupMembership(group=group, user_id=member_id) for member_id in member_ids]
            GroupMembership.objects.bulk_create(memberships)
        return group

    def update(self, instance, validated_data):
        member_ids = validated_data.pop('member_ids', None)
        instance = super().update(instance, validated_data)

        if member_ids is not None:
            # Clear existing members and add new ones
            instance.memberships.all().delete()
             # Validation done in validate_member_ids
            if member_ids:
                memberships = [GroupMembership(group=instance, user_id=member_id) for member_id in member_ids]
                GroupMembership.objects.bulk_create(memberships)
        return instance
