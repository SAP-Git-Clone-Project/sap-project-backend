from django.db import models
from django.conf import settings

class Document(models.Model):
    id = models.BigAutoField(primary_key=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length = 128)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        managed = False
        #db_table = 'users'

class Version(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending_approval', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    id = models.BigAutoField(primary_key=True)
    document = models.ForeignKey(Document, on_delete=models.CASCADE)
    version_number = models.IntegerField()
    content = models.TextField() # TODO: Figure out whether to use TextField or FileField here

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    parent_version = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    file_path = models.CharField(max_length=512)
    file_size = models.BigIntegerField()
    checksum = models.CharField(max_length=255)

    class Meta:
        managed = False
        #db_table = 'users'

class DocumentPermission(models.Model):
    PERMISSION_CHOICES = [
        ('read', 'Read'),
        ('write', 'Write'),
        ('delete', 'Delete'),
        ('approve', 'Approve'),
    ]

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    document = models.ForeignKey(Document, on_delete=models.CASCADE)
    permission_type = models.CharField(max_length=10, choices=PERMISSION_CHOICES)
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        #db_table = 'users'

class Review(models.Model):
    STATUS_CHOICES = [
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('pending', 'Pending'),
    ]

    id = models.BigAutoField(primary_key=True)
    version = models.ForeignKey('Version', on_delete=models.CASCADE)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    review_status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    comments = models.TextField(blank=True, null=True)
    reviewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        #db_table = 'users'
