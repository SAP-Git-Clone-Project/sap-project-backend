import uuid
from django.db import models
from django.conf import settings
from document_permissions.models import DocumentPermissionRequestModel

class NotificationModel(models.Model):
    # NOTE: Secure UUID used for notification identification
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # NOTE: User who receives the alert
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )

    # NOTE: User who triggered the notification or System if null
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications_triggered",  # Updated from actions_triggered
        null=True,
        blank=True,
    )

    # NOTE: Description of the action like shared or approved
    verb = models.CharField(max_length=255)

    # NOTE: Link to the specific document that triggered the alert
    target_document = models.ForeignKey(
        "documents.DocumentModel", on_delete=models.CASCADE, null=True, blank=True
    )

    permission_request = models.ForeignKey(
        DocumentPermissionRequestModel,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications"
    )

    # NOTE: Status tracking for the notification
    is_read = models.BooleanField(default=False)

    # NOTE: Automatic timestamping for sorting and history
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications"
        # NOTE: Newest alerts appear first in querysets
        ordering = ["-created_at"]

    def __str__(self):
        # NOTE: Formats notification for admin display
        user_name = self.user.username if self.user else "System"
        return f"{user_name} {self.verb} for {self.recipient}"
