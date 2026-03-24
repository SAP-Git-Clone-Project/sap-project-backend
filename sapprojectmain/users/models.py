import uuid
from django.db import models
from django.contrib.auth.models import (
    AbstractBaseUser,
    PermissionsMixin,
    BaseUserManager,
)

# USER MANAGER
class UserManager(BaseUserManager):
    def create_user(self, username, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")

        if not username:
            raise ValueError("Username is required")

        email = self.normalize_email(email).lower()

        user = self.model(username=username, email=email, **extra_fields)

        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_enabled", True)

        return self.create_user(username, email, password, **extra_fields)


# CUSTOM USER MODEL
class UserModel(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    first_name = models.CharField(max_length=80, blank=False, null=False)
    last_name = models.CharField(max_length=80, blank=False, null=False)

    username = models.CharField(max_length=150, unique=True, blank=False, null=False)
    email = models.EmailField(unique=True, blank=False, null=False)

    password = models.CharField(max_length=255, blank=False, null=False)

    avatar = models.TextField(
        blank=True,
        null=True,
        default="https://res.cloudinary.com/dbgpxmjln/image/upload/v1766143170/deafult-avatar_tyvazc.png",
    )

    is_enabled = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        db_table = "users"
        constraints = [
            models.UniqueConstraint(fields=["email"], name="unique_email"),
            models.UniqueConstraint(fields=["username"], name="unique_username"),
        ]

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.lower()
        super().save(*args, **kwargs)
