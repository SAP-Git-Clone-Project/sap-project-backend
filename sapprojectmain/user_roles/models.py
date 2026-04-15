import uuid
from django.db import models
from django.conf import settings

class Role(models.Model):
    class RoleName(models.TextChoices):
        READER = 'reader', 'Reader'
        REVIEWER = 'reviewer', 'Reviewer'
        WRITER = 'writer', 'Writer'
        AUTHOR = 'author', 'Author'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='roles'
    )
    role_name = models.CharField(
        max_length=20,
        choices=RoleName.choices,
    )
    description = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'Roles'

    def __str__(self):
        return f"{self.user} - {self.get_role_name_display()}"
