import uuid

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import TimestampedModel
from apps.core.models import Tenant  # Import Tenant


class UserManager(BaseUserManager):
    """Define a model manager for User model with no username field."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        """Create and save a User with the given email and password."""
        if not email:
            raise ValueError("The given email must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        """Create and save a regular User with the given email and password."""
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        """Create and save a SuperUser with the given email and password."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)  # Superusers are Admins

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        # Superusers might not belong to a specific tenant or belong to a default one
        extra_fields.pop("tenant", None)

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser, TimestampedModel):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", _("Admin")
        INSTRUCTOR = "INSTRUCTOR", _("Instructor")
        LEARNER = "LEARNER", _("Learner")
        # CONTENT_CREATOR = 'CONTENT_CREATOR', _('Content Creator')

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", _("Active")
        INVITED = "INVITED", _("Invited")  # User invited but not yet logged in
        SUSPENDED = "SUSPENDED", _("Suspended")  # User access revoked temporarily
        DELETED = "DELETED", _("Deleted")  # Soft delete marker

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = None  # Use email instead
    email = models.EmailField(_("email address"), unique=True, db_index=True)
    first_name = models.CharField(_("first name"), max_length=150, blank=True)
    last_name = models.CharField(_("last name"), max_length=150, blank=True)

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.LEARNER)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.INVITED
    )  # Default to Invited? Or Active?

    # Link user to a tenant. Non-superusers MUST belong to a tenant.
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,  # Prevent tenant deletion if users exist? Or CASCADE?
        null=True,  # Allow null only for superusers
        blank=True,
        related_name="users",
    )

    # LTI/SSO Identifiers (optional, depends on integration details)
    lti_user_id = models.CharField(
        max_length=255, null=True, blank=True, unique=True, db_index=True
    )
    sso_provider = models.CharField(
        max_length=50, null=True, blank=True
    )  # e.g., 'saml_idp1', 'google-oauth2'
    sso_subject_id = models.CharField(
        max_length=255, null=True, blank=True, db_index=True
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    objects = UserManager()

    def __str__(self):
        return self.email

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def save(self, *args, **kwargs):
        # Ensure non-superusers always have a tenant
        if not self.is_superuser and self.tenant is None:
            # Try to associate based on context, or raise error if needed
            # This logic might be better placed in the view/service creating the user
            # For now, let's prevent saving without a tenant for non-superusers
            raise ValueError("Non-superuser must be associated with a Tenant.")
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = _("User")
        verbose_name_plural = _("Users")
        ordering = ["email"]
        # Add constraint if sso_provider and sso_subject_id should be unique together
        # unique_together = (('sso_provider', 'sso_subject_id'),)


class UserProfile(TimestampedModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True)
    bio = models.TextField(blank=True)
    language = models.CharField(
        max_length=10, default="en", blank=True
    )  # User language preference
    timezone = models.CharField(
        max_length=100, default="UTC", blank=True
    )  # User timezone preference
    # Store other non-critical preferences
    preferences = models.JSONField(
        default=dict, blank=True
    )  # e.g., notification settings summary, theme choice

    def __str__(self):
        return f"Profile for {self.user.email}"


class LearnerGroup(TimestampedModel):
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="learner_groups"
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    members = models.ManyToManyField(
        User,
        through="GroupMembership",
        related_name="learner_groups",
        # Limit choices to users within the same tenant
        limit_choices_to={
            "tenant": models.F("tenant")
        },  # Requires adjusting if tenant is nullable
    )

    def __str__(self):
        return f"{self.name} ({self.tenant.name})"

    class Meta:
        unique_together = ("tenant", "name")  # Group names unique per tenant
        verbose_name = _("Learner Group")
        verbose_name_plural = _("Learner Groups")
        ordering = ["tenant__name", "name"]


class GroupMembership(TimestampedModel):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="group_memberships"
    )
    group = models.ForeignKey(
        LearnerGroup, on_delete=models.CASCADE, related_name="memberships"
    )
    date_joined = models.DateTimeField(auto_now_add=True)
    # role_in_group = models.CharField(max_length=50, default='member', blank=True) # Optional

    def __str__(self):
        return f"{self.user.email} in {self.group.name}"

    class Meta:
        unique_together = ("user", "group")
        ordering = ["group__name", "user__email"]
        verbose_name = _("Group Membership")
        verbose_name_plural = _("Group Memberships")


# --- Signals ---
# Optional: Create UserProfile automatically when a User is created
# Define this in signals.py and import in apps.py ready() method
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)


def save_user_profile(sender, instance, **kwargs):
    try:
        instance.profile.save()
    except UserProfile.DoesNotExist:
        # Handle case where profile might somehow not exist (e.g., during data migration)
        UserProfile.objects.create(user=instance)
