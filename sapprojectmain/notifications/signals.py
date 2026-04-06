from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.db import transaction
import logging

from document_permissions.models import DocumentPermissionModel
from reviews.models import ReviewModel
from versions.models import VersionsModel
from .models import NotificationModel

logger = logging.getLogger(__name__)


# --- HELPER: STORE OLD STATUS ---
# Used to detect if a review status actually changed (e.g., PENDING -> APPROVED)
@receiver(pre_save, sender=ReviewModel)
def store_old_review_status(sender, instance, **kwargs):
    if instance.pk:
        try:
            instance._old_status = ReviewModel.objects.get(pk=instance.pk).review_status
        except ReviewModel.DoesNotExist:
            instance._old_status = None


# --- CONNECTION 1: RESIGNATION ---
# Notifies document owner when a collaborator leaves
@receiver(post_delete, sender=DocumentPermissionModel)
def notify_owner_of_resignation(sender, instance, **kwargs):
    try:
        transaction.on_commit(
            lambda: NotificationModel.objects.create(
                recipient=instance.document.created_by,
                user=instance.user,  # User who resigned
                verb=f"resigned from their {instance.permission_type} role for",
                target_document=instance.document,
            )
        )
    except Exception as e:
        logger.error(f"Notification error (resignation): {e}")


# --- CONNECTION 2: REVIEW DECISION ---
# Notifies the version creator when a reviewer approves or rejects
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
                user=instance.reviewer,  # Reviewer who made the choice
                verb=f"{instance.review_status.lower()} your version of",
                target_document=instance.version.document,
            )
        )


# --- CONNECTION 3: ACCESS GRANTED ---
# Notifies a user when they are added to a document
@receiver(post_save, sender=DocumentPermissionModel)
def notify_access_granted(sender, instance, created, **kwargs):
    if created:
        transaction.on_commit(
            lambda: NotificationModel.objects.create(
                recipient=instance.user,  # User getting access
                user=instance.document.created_by,  # Owner granting access
                verb=f"granted you {instance.permission_type} access to",
                target_document=instance.document,
            )
        )


# --- CONNECTION 4: NEW VERSION & REVIEW REQUEST ---
# Dual-purpose signal for uploads and notifying assigned reviewers
@receiver(post_save, sender=VersionsModel)
def notify_of_new_version(sender, instance, created, **kwargs):
    if created:
        # 1. Notify Document Owner if someone else uploads a version
        if instance.created_by != instance.document.created_by:
            transaction.on_commit(
                lambda: NotificationModel.objects.create(
                    recipient=instance.document.created_by,
                    user=instance.created_by,
                    verb="uploaded a new version to",
                    target_document=instance.document,
                )
            )

        # 2. Notify Reviewer if a review record exists for this version
        # We use .first() to get the most relevant review assignment
        review = (
            ReviewModel.objects.filter(version=instance).order_by("-created_at").first()
        )

        if review and review.reviewer:
            transaction.on_commit(
                lambda: NotificationModel.objects.create(
                    recipient=review.reviewer,
                    user=instance.created_by,
                    verb="requested a review for",
                    target_document=instance.document,
                )
            )
