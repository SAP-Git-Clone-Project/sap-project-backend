import uuid
from django.db import models
from django.db.models import Q
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from documents.models import DocumentModel

# DOCUMENT PERMISSIONS MANAGER
class DocumentPermissionManager(models.Manager):
    def create_document_permission(self, **extra_fields):
        # TODO: Check if permission_type is allowed for the role the user has

        document_permission = self.model(**extra_fields)
        document_permission.save(using=self._db)
        return document_permission

# DOCUMENT PERMISSION MODEL
class DocumentPermissionModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user_id = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="document_permissions_user")
    document_id = models.ForeignKey(DocumentModel, on_delete=models.CASCADE, related_name="document_permissions_document")

    class PermissionType(models.TextChoices):
        READ    = "READ", _("READ")
        WRITE   = "WRITE", _("WRITE")
        APPROVE = "APPROVE", _("APPROVE")
        DELETE  = "DELETE", _("DELETE")
    
    permission_type = models.CharField(max_length=16, choices=PermissionType.choices, default=PermissionType.READ)

    granted_at = models.DateTimeField(auto_now_add=True)

    objects = DocumentPermissionManager()
    
    class Meta:
        db_table = "document_permissions"
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "document_id", "permission_type"],
                name="unique_user_document_permission"
            )
        ]
        indexes = [
            models.Index(fields=["user_id", "document_id"]),
        ]
    
    def __str__(self):
        return self.permission_type
