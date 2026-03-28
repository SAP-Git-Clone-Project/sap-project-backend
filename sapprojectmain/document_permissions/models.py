import uuid
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from documents.models import DocumentModel


# DOCUMENT PERMISSIONS MODEL DEFINITION
class DocumentPermissionModel(models.Model):
    # NOTE: Definitive mapping of available access levels
    class PermissionType(models.TextChoices):
        READ = "READ", _("Read Only")
        WRITE = "WRITE", _("Write/Edit")
        APPROVE = "APPROVE", _("Approve/Review")
        DELETE = "DELETE", _("Full Owner/Delete")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # IMP: CASCADE ensures permissions are purged if the user is deleted
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="document_permissions",
    )

    # IMP: Permissions are tied directly to the lifecycle of the document
    document = models.ForeignKey(
        DocumentModel, on_delete=models.CASCADE, related_name="document_permissions"
    )

    permission_type = models.CharField(
        max_length=16, choices=PermissionType.choices, default=PermissionType.READ
    )

    # NOTE: Tracking the timing of the initial grant and subsequent updates
    granted_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "document_permissions"
        # SECURITY: Prevent duplicate permission entries for the same user-document pair
        constraints = [
            models.UniqueConstraint(
                fields=["user", "document"], name="unique_user_document_permission"
            )
        ]
        # PERFORMANCE: Indexing frequently queried fields to speed up access checks
        indexes = [
            models.Index(fields=["user", "document"]),
        ]

    def __str__(self):
        return f"{self.user.username} -> {self.document.title} ({self.permission_type})"


# NOTE: Ensure the migration includes the unique constraint to maintain data integrity
