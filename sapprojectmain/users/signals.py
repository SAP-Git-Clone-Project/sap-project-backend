from django.db.models.signals import post_save
from django.dispatch import receiver

from user_roles.models import Role, UserRole
from .models import UserModel


@receiver(post_save, sender=UserModel)
def assign_default_reader_role(sender, instance, created, **kwargs):
    if not created:
        return

    reader_role, _ = Role.objects.get_or_create(
        role_name=Role.RoleName.READER,
        defaults={"description": "Default role for all users."},
    )
    UserRole.objects.get_or_create(user=instance, role=reader_role)
