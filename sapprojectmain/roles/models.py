import uuid
from django.db import models
from django.conf import settings


# Create your models here.
class RolesModel(models.Model):

    ROLE_CHOICES = [
        ("author", "Author"),
        ("reviewer", "Reviewer"),
        ("reader", "Reader"),
        ("administrator", "Administrator"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    role_name = models.CharField(
        max_length=50, choices=ROLE_CHOICES, unique=True, blank=False, null=False
    )

    description = models.TextField(blank=True)

    class Meta:
        db_table = "roles"

    def __str__(self):
        return self.role_name


class UserRolesModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user_roles"
    )

    role = models.ForeignKey(
        RolesModel, on_delete=models.CASCADE, related_name="user_roles"
    )

    assigned_at = models.DateTimeField(auto_now_add=True)

    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="assigned_roles",
    )

    class Meta:
        db_table = "user_roles"
        unique_together = ("user", "role")

    def __str__(self):
        return f"{self.user.email} - {self.role.role_name}"
