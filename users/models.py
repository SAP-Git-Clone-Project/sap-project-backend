from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    id = models.BigAutoField(primary_key=True)
    email = models.CharField(max_length=128)
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        #db_table = 'users'
    
class Role(models.Model):
    ROLE_CHOICES = [
        ('author', 'Author'),
        ('reviewer', 'Reviewer'),
        ('reader', 'Reader'),
        ('administrator', 'Administrator'),
    ]

    id = models.BigAutoField(primary_key=True)
    role_name = models.CharField(max_length=20, choices=ROLE_CHOICES)
    description = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        #db_table = 'users'

class UserRole(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='role_assigned_by')

    class Meta:
        managed = False
        #db_table = 'users'
