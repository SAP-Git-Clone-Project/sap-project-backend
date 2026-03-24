import uuid
from django.db import models
from django.db.models import Q
from django.conf import settings

# DOCUMENT QUERY SET
class DocumentQuerySet(models.QuerySet):
    def delete(self):
        return super().update(is_deleted=True)

    def alive(self):
        return super().filter(is_deleted=False)

# DOCUMENT MANAGER
class DocumentManager(models.Manager):
    def create_document(self, created_by_uuid, title, **extra_fields):
        if not title:
            raise ValueError("Title is required")
        
        document = self.model(title=title, **extra_fields)
        document.created_by = created_by_uuid

        document.save(using=self.__db)
        return document

    def get_queryset(self):
        return DocumentQuerySet(self.model, using=self._db)
    
    def get_queryset_without_deleted(self):
        return self.get_queryset().alive()

# DOCUMENT MODEL
class DocumentModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    title = models.CharField(max_length=128)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="documents")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    is_deleted = models.BooleanField(default=False)
    
    objects = DocumentManager()

    class Meta:
        db_table = "documents"
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "title"],
                condition=Q(is_deleted=False),
                name="unique_user_title")
        ]
    
        
    def __str__(self):
        return self.title
        
    def delete(self, *args, **kwargs):
        self.is_deleted = True
        self.save(*args, **kwargs)

    def restore(self, *args, **kwargs):
        self.is_deleted = False
        self.save(*args, **kwargs)
        
