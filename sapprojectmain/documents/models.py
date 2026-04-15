import uuid
from django.db import models
from django.db.models import Q
from django.conf import settings
from django.db import transaction

# --- DOCUMENT QUERY SET ---
class DocumentQuerySet(models.QuerySet):
    def delete(self):
        # NOTE: Updates flag instead of removing row for soft delete
        return self.update(is_deleted=True)

    def active(self):
        # NOTE: Filters for documents not marked as deleted
        return self.filter(is_deleted=False)


# --- DOCUMENT MANAGER ---
class DocumentManager(models.Manager):
    def get_queryset(self):
        return DocumentQuerySet(self.model, using=self._db).select_related('created_by')

    def active_documents(self):
        return self.get_queryset().active()
    
    def visible_documents(self, user):
        from document_permissions.models import DocumentPermissionModel

        has_permission = DocumentPermissionModel.objects.filter(document=models.OuterRef("pk"), user=user)

        return self.active_documents().annotate(
            user_has_permission=models.Exists(has_permission)
        ).filter(
            Q(created_by=user) | Q(user_has_permission=True)
        ).distinct()

    def create_document(self, created_by, title, **extra_fields):
        # NOTE: Handles document creation and initial owner permissions
        if not title:
            raise ValueError("Title is required")

        # IMP: Atomic ensure doc and owner permission are created together
        with transaction.atomic():
            document = self.model(title=title, created_by=created_by, **extra_fields)
            document.save(using=self._db)

            # NOTE: Dynamic lookup prevents circular imports between apps
            PermissionModel = self.model.document_permissions.rel.related_model
            PermissionModel.objects.create(
                user=created_by, document=document, permission_type="DELETE"
            )

        return document


# --- DOCUMENT MODEL ---
class DocumentModel(models.Model):
    # NOTE: UUID used for secure resource identification
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=128)

    # NOTE: Permanent owner used for storage paths and auditing
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_documents",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)

    objects = DocumentManager()

    class Meta:
        db_table = "documents"
        constraints = [
            # SECURITY: Prevents users from having duplicate titles on active docs
            models.UniqueConstraint(
                fields=["created_by", "title"],
                condition=Q(is_deleted=False),
                name="unique_user_active_title",
            )
        ]

    def __str__(self):
        return self.title

    def delete(self, *args, **kwargs):
        # NOTE: Sets is_deleted flag for instance-level soft delete
        self.is_deleted = True
        self.save()

    def restore(self):
        # NOTE: Resets is_deleted flag to bring back document
        self.is_deleted = False
        self.save()

# DOCUMENT DELETION REQUEST MODEL
class DocumentDeletionRequestModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(DocumentModel, on_delete=models.CASCADE, related_name="deletion_requests")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=10,
        choices=[
            ("PENDING", "Pending"),
            ("APPROVED", "Approved"),
            ("REJECTED", "Rejected"),
        ],
        default="PENDING",
    )

    class Meta:
        db_table = "document_deletion_requests"
        unique_together = ("document", "requested_by")

    def __str__(self):
        return f"Deletion request for {self.document.title} by {self.requested_by.username}"
    
# DOCUMENT DELETION DECISION MODEL
class DocumentDeletionDecisionModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(
        DocumentModel,
        on_delete=models.CASCADE,
        related_name="deletion_decisions",
    )
    reviewer_id = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    decision = models.CharField(null=True, blank=True,
        max_length=10,
        choices=[
            ("APPROVED", "Approved"),
            ("REJECTED", "Rejected"),
            ("PENDING", "Pending"),
        ],
        default="PENDING",
    )

    class Meta:
        db_table = "document_deletion_decisions"
        unique_together = ("document", "reviewer_id")

    def __str__(self):
        return f"{self.reviewer_id.username} {self.decision} deletion of {self.document.title}"