import uuid
from django.db import models
from django.conf import settings


class NotificationModel(models.Model):
    # NOTE: Secure UUID used for notification identification
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # NOTE: User who receives the alert
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )

    # NOTE: User who triggered the notification or System if null
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="actions_triggered",
        null=True,
        blank=True,
    )

    # NOTE: Description of the action like shared or approved
    verb = models.CharField(max_length=255)

    # NOTE: Link to the specific document that triggered the alert
    target_document = models.ForeignKey(
        "documents.DocumentModel", on_delete=models.CASCADE, null=True, blank=True
    )

    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications"
        # NOTE: Newest alerts appear first in querysets
        ordering = ["-created_at"]

    def __str__(self):
        # NOTE: Formats notification for admin display
        actor_name = self.actor.username if self.actor else "System"
        return f"{actor_name} {self.verb} for {self.recipient}"
