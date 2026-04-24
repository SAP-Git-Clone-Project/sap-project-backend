import uuid
from django.db import models
from django.conf import settings
from documents.models import DocumentModel
from versions.models import VersionsModel

# AUDIT LOG MODEL DEFINITION
class AuditLogModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # NOTE: SET_NULL ensures audit trails persist even if the actor is deleted
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        db_column="user_id",
        related_name="audit_logs",
    )

    # NOTE: Foreign keys link directly to document and version for relational integrity
    document = models.ForeignKey(
        DocumentModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="document_id",
    )

    # NOTE: Explicit db_column mapping used to match existing database schema
    version = models.ForeignKey(
        VersionsModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="version_id",
    )

    # NOTE: action_type stored as string for compatibility across different DB backends
    action_type = models.CharField(max_length=50)

    # NOTE: Capturing origin IP for compliance and security monitoring
    ip_address = models.CharField(max_length=45, null=True, blank=True)

    # NOTE: timestamp captures the exact moment of the logged event
    timestamp = models.DateTimeField(auto_now_add=True)

    # NOTE: Metadata field for supplemental event details or debugging context
    description = models.TextField(null=True, blank=True)

    class Meta:
        # NOTE: Explicit table name mapping to the 'audit_log' database table
        db_table = "audit_log"

        # NOTE: Orders logs by most recent first
        ordering = ["-timestamp"]

    # NOTE: String representation of the audit log entry for easy identification in admin interfaces and debugging in the django admin panel
    def __str__(self):
        return f"{self.action_type} - {self.timestamp}"