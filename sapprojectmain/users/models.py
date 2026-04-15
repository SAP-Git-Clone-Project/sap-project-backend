import uuid
from django.db import models
from django.contrib.auth.models import (
    AbstractBaseUser,
    PermissionsMixin,
    BaseUserManager,
)
from django.conf import settings
from .models import RoleChoices


class UserManager(BaseUserManager):
    def create_user(self, email, username, password=None, **extra_fields):
        # NOTE: Ensures email is provided and normalized to lowercase
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, username=username, **extra_fields)

        # NOTE: Hashes the password before saving to the database
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, username, password=None, **extra_fields):
        # NOTE: Helper to create an account with administrative privileges
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, username, password, **extra_fields)


class UserModel(AbstractBaseUser, PermissionsMixin):
    # NOTE: Secure UUID used for user identification
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=50, unique=True)
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)

    # NOTE: Stores the link to the user profile image with a default fallback
    avatar = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        default="https://res.cloudinary.com/dbgpxmjln/image/upload/v1766143170/deafult-avatar_tyvazc.png",
    )

    # NOTE: Flags for account status and system access levels
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    # NOTE: Configures email as the primary login identifier
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class RoleChoices(models.TextChoices):
        VIEWER = "VIEWER", "Viewer"        # Read-only access across the system
        EDITOR = "EDITOR", "Editor"        # Can create/edit documents
        REVIEWER = "REVIEWER", "Reviewer"  # Can approve/reject versions
        ADMIN = "ADMIN", "Admin"           # Staff-level system management
        SUPERADMIN = "SUPERADMIN", "Super Admin"  # Full access
 
    class UserRoleModel(models.Model):
        id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 
        user = models.OneToOneField(
            settings.AUTH_USER_MODEL,
            on_delete=models.CASCADE,
            related_name="user_role",
    )
 
        role = models.CharField(
            max_length=20,
            choices=RoleChoices.choices,
            default=RoleChoices.VIEWER,
    )
 
        assigned_by = models.ForeignKey(
            settings.AUTH_USER_MODEL,
            on_delete=models.SET_NULL,
            null=True,
            blank=True,
            related_name="roles_assigned",
    )

    assigned_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = "users"
        ordering = ["assigned_at"]

    def __str__(self):
        # NOTE: Returns email for user identification in admin and logs
        return f"{self.user.email} → {self.role}"

    