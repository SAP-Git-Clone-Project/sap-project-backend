import uuid
from django.db import models
from django.conf import settings


class Role(models.Model):
    class RoleName(models.TextChoices):
        READER = "reader", "Reader"
        REVIEWER = "reviewer", "Reviewer"
        WRITER = "writer", "Writer"
        AUTHOR = "author", "Author"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role_name = models.CharField(
        max_length=20,
        choices=RoleName.choices,
        unique=True,
    )
    description = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "roles"
        indexes = [models.Index(fields=["role_name"])]

    def __str__(self):
        return self.get_role_name_display()


class UserRole(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user_roles"
    )
    role = models.ForeignKey(
        Role, on_delete=models.CASCADE, related_name="user_roles"
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="assigned_user_roles",
        null=True,
        blank=True,
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_roles"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "role"], name="unique_user_role_assignment"
            )
        ]
        indexes = [models.Index(fields=["user"]), models.Index(fields=["role"])]

    def __str__(self):
        return f"{self.user} - {self.role.role_name}"
