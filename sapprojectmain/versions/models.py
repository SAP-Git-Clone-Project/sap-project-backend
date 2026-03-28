import uuid
from django.db import models
from django.conf import settings
from django.db import transaction


class VersionStatus(models.TextChoices):
    # NOTE: Defines the lifecycle states of a document version
    DRAFT = "draft", "Draft"
    PENDING = "pending_approval", "Pending Approval"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class VersionsModel(models.Model):
    # NOTE: Secure UUID used for version identification
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # NOTE: Link to the parent document using app-label to prevent circularity
    document = models.ForeignKey(
        "documents.DocumentModel", on_delete=models.CASCADE, related_name="versions"
    )

    # NOTE: Tracks the specific user who uploaded this iteration
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_versions",
    )

    version_number = models.IntegerField()
    content = models.TextField(blank=True, null=True)

    # NOTE: Current approval state of this specific version
    status = models.CharField(
        max_length=20, choices=VersionStatus.choices, default=VersionStatus.DRAFT
    )

    # NOTE: Self-referential link to the previous version for history tracking
    parent_version = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="child_versions",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=False)

    # NOTE: Storage metadata for Cloudinary and file integrity checks
    file_path = models.URLField(max_length=500, blank=True, null=True)
    file_size = models.BigIntegerField(blank=True, null=True)
    checksum = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = "versions"
        # NOTE: Ensures no duplicate version numbers exist for a single document
        unique_together = ("document", "version_number")
        ordering = ["-version_number"]

    def __str__(self):
        # NOTE: Formats version for admin display and logging
        return f"{self.document.title} - V{self.version_number} ({self.status})"

    def generate_upload_path(self):
        # NOTE: Generates structured storage paths based on owner and document IDs
        owner_id = self.document.created_by.id
        doc_id = self.document.id
        return f"documents/{owner_id}/{doc_id}/v{self.version_number}"

    def save(self, *args, **kwargs):
        # NOTE: Auto-increment version number logic with row-level locking
        if not self.version_number:
            with transaction.atomic():
                last_version = (
                    VersionsModel.objects.filter(document=self.document)
                    .select_for_update()
                    .order_by("version_number")
                    .last()
                )
                self.version_number = (
                    (last_version.version_number + 1) if last_version else 1
                )

        # SECURITY: Ensures only approved versions can be marked as active
        if self.is_active and self.status != VersionStatus.APPROVED:
            self.is_active = False

        # IMP: Singleton logic to ensure only one version is active per document
        if self.is_active:
            with transaction.atomic():
                VersionsModel.objects.filter(document=self.document).exclude(
                    id=self.id
                ).update(is_active=False)

        super().save(*args, **kwargs)
