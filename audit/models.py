from django.db import models
from django.conf import settings

class AuditLog(models.Model):
    ACTION_CHOICES = [
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('create_document', 'Create Document'),
        ('create_version', 'Create Version'),
        ('delete_document', 'Delete Document'),
        ('export', 'Export'),
        ('approve_version', 'Approve Version'),
        ('reject_version', 'Reject Version'),
        ('update_metadata', 'Update Metadata'),
    ]

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    document = models.ForeignKey('documents.Document', on_delete=models.SET_NULL, null=True)
    version = models.ForeignKey('documents.Version', on_delete=models.SET_NULL, null=True)

    action_type = models.CharField(max_length=30, choices=ACTION_CHOICES)
    ip_address = models.GenericIPAddressField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        #db_table = 'users'
