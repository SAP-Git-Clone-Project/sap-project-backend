from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.db import transaction
import logging

from document_permissions.models import DocumentPermissionModel
from reviews.models import ReviewModel
from versions.models import VersionsModel
from .models import NotificationModel

logger = logging.getLogger(__name__)


# --- HELPER: STORE OLD STATUS (FIX) ---
@receiver(pre_save, sender=ReviewModel)
def store_old_review_status(sender, instance, **kwargs):
    if instance.pk:
        try:
            instance._old_status = ReviewModel.objects.get(pk=instance.pk).review_status
        except ReviewModel.DoesNotExist:
            instance._old_status = None


# --- CONNECTION 1 ---
@receiver(post_delete, sender=DocumentPermissionModel)
def notify_owner_of_resignation(sender, instance, **kwargs):
    try:
        transaction.on_commit(
            lambda: NotificationModel.objects.create(
                recipient=instance.document.created_by,
                actor=instance.user,
                verb=f"resigned from their {instance.permission_type} role for",
                target_document=instance.document,
            )
        )
    except Exception as e:
        logger.error(f"Notification error (resignation): {e}")


# --- CONNECTION 2 ---
@receiver(post_save, sender=ReviewModel)
def notify_review_decision(sender, instance, created, **kwargs):
    if created:
        return

    old_status = getattr(instance, "_old_status", None)

    if old_status != instance.review_status and instance.review_status in [
        "APPROVED",
        "REJECTED",
    ]:
        transaction.on_commit(
            lambda: NotificationModel.objects.create(
                recipient=instance.version.created_by,
                actor=instance.reviewer,
                verb=f"{instance.review_status.lower()} your version of",
                target_document=instance.version.document,
            )
        )


# --- CONNECTION 3 ---
@receiver(post_save, sender=DocumentPermissionModel)
def notify_access_granted(sender, instance, created, **kwargs):
    if created:
        transaction.on_commit(
            lambda: NotificationModel.objects.create(
                recipient=instance.user,
                actor=instance.document.created_by,
                verb=f"granted you {instance.permission_type} access to",
                target_document=instance.document,
            )
        )


# --- CONNECTION 4 ---
@receiver(post_save, sender=VersionsModel)
def notify_of_new_version(sender, instance, created, **kwargs):
    if created:
        if instance.created_by != instance.document.created_by:
            transaction.on_commit(
                lambda: NotificationModel.objects.create(
                    recipient=instance.document.created_by,
                    actor=instance.created_by,
                    verb="uploaded a new version to",
                    target_document=instance.document,
                )
            )

        review = ReviewModel.objects.filter(version=instance).order_by("-id").first()

        if review:
            transaction.on_commit(
                lambda: NotificationModel.objects.create(
                    recipient=review.reviewer,
                    actor=instance.created_by,
                    verb="requested a review for",
                    target_document=instance.document,
                )
            )
