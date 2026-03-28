from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db import transaction

from document_permissions.models import DocumentPermissionModel
from reviews.models import ReviewModel
from versions.models import VersionsModel
from .models import NotificationModel


# --- CONNECTION 1 ---
@receiver(post_delete, sender=DocumentPermissionModel)
def notify_owner_of_resignation(sender, instance, **kwargs):
    # NOTE: Alerts owner when a user voluntarily leaves a document
    try:
        # IMP: Ensures notification only sends if deletion transaction succeeds
        transaction.on_commit(
            lambda: NotificationModel.objects.create(
                recipient=instance.document.created_by,
                actor=instance.user,
                verb=f"resigned from their {instance.permission_type} role for",
                target_document=instance.document,
            )
        )
    except Exception:
        pass


# --- CONNECTION 2 ---
@receiver(post_save, sender=ReviewModel)
def notify_review_decision(sender, instance, created, **kwargs):
    # NOTE: Alerts version creator when a reviewer makes a decision
    if not created and instance.review_status in ["APPROVED", "REJECTED"]:
        NotificationModel.objects.create(
            recipient=instance.version.created_by,
            actor=instance.reviewer,
            verb=f"{instance.review_status.lower()} your version of",
            target_document=instance.version.document,
        )


# --- CONNECTION 3 ---
@receiver(post_save, sender=DocumentPermissionModel)
def notify_access_granted(sender, instance, created, **kwargs):
    # NOTE: Alerts user when they receive new document permissions
    if created:
        NotificationModel.objects.create(
            recipient=instance.user,
            actor=instance.document.created_by,
            verb=f"granted you {instance.permission_type} access to",
            target_document=instance.document,
        )


# --- CONNECTION 4 ---
@receiver(post_save, sender=VersionsModel)
def notify_of_new_version(sender, instance, created, **kwargs):
    # NOTE: Alerts relevant parties when a new version is uploaded
    if created:
        # NOTE: Notify owner if someone else performs the upload
        if instance.created_by != instance.document.created_by:
            NotificationModel.objects.create(
                recipient=instance.document.created_by,
                actor=instance.created_by,
                verb="uploaded a new version to",
                target_document=instance.document,
            )

        # NOTE: Notify assigned reviewer to check the new version
        review = ReviewModel.objects.filter(version=instance).first()
        if review:
            NotificationModel.objects.create(
                recipient=review.reviewer,
                actor=instance.created_by,
                verb="requested a review for",
                target_document=instance.document,
            )
