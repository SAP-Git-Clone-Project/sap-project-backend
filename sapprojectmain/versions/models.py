import uuid
from django.db import models


class VersionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PENDING = "pending_approval", "Pending Approval"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class Versions(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(
        "documents.DocumentModel", on_delete=models.CASCADE, related_name="versions"
    )
    version_number = models.IntegerField()
    content = models.TextField(blank=True, null=True)
    status = models.CharField(
        max_length=20, choices=VersionStatus.choices, default=VersionStatus.DRAFT
    )
    parent_version = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=False)  # Should only be True if Approved
    file_path = models.URLField(max_length=500, blank=True, null=True)
    file_size = models.BigIntegerField(blank=True, null=True)
    checksum = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = "versions"
