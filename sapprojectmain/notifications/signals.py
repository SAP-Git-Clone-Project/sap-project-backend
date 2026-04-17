from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.db import transaction
import logging

from document_permissions.models import DocumentPermissionModel
from reviews.models import ReviewModel
from versions.models import VersionsModel
from user_roles.models import UserRole
from .models import NotificationModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HELPER
# ---------------------------------------------------------------------------
def _safe_notify(**kwargs):
    """
    Wraps NotificationModel.objects.create in its own savepoint so a DB error
    inside a post-commit callback can never corrupt an outer connection state.
    """
    try:
        with transaction.atomic():
            NotificationModel.objects.create(**kwargs)
    except Exception as e:
        logger.error(f"Notification create failed: {e}", exc_info=True)


# ---------------------------------------------------------------------------
# STORE OLD STATUS
# ---------------------------------------------------------------------------
@receiver(pre_save, sender=ReviewModel)
def store_old_review_status(sender, instance, **kwargs):
    if instance.pk:
        try:
            instance._old_status = ReviewModel.objects.get(pk=instance.pk).review_status
        except ReviewModel.DoesNotExist:
            instance._old_status = None


# ---------------------------------------------------------------------------
# CONNECTION 1 — RESIGNATION
# Notifies document owner when a collaborator leaves
# ---------------------------------------------------------------------------
@receiver(post_delete, sender=DocumentPermissionModel)
def notify_owner_of_resignation(sender, instance, **kwargs):
    # Eagerly resolve FKs NOW — after commit the related rows may be gone
    try:
        recipient = instance.document.created_by
        actor     = instance.user
        perm_type = instance.permission_type
        document  = instance.document
    except Exception as e:
        logger.warning(f"Resignation notification skipped (FK resolution failed): {e}")
        return

    transaction.on_commit(lambda: _safe_notify(
        recipient=recipient,
        user=actor,
        verb=f"resigned from their {perm_type} role for",
        target_document=document,
    ))


# ---------------------------------------------------------------------------
# CONNECTION 2 — REVIEW DECISION
# Notifies the version creator when a reviewer approves or rejects
# ---------------------------------------------------------------------------
@receiver(post_save, sender=ReviewModel)
def notify_review_decision(sender, instance, created, **kwargs):
    if created:
        return

    old_status = getattr(instance, "_old_status", None)

    if old_status == instance.review_status:
        return

    if instance.review_status not in ("APPROVED", "REJECTED"):
        return

    try:
        recipient = instance.version.created_by
        actor     = instance.reviewer
        verb      = f"{instance.review_status.lower()} your version of"
        document  = instance.version.document
    except Exception as e:
        logger.warning(f"Review decision notification skipped (FK resolution failed): {e}")
        return

    transaction.on_commit(lambda: _safe_notify(
        recipient=recipient,
        user=actor,
        verb=verb,
        target_document=document,
    ))


# ---------------------------------------------------------------------------
# CONNECTION 3 — ACCESS GRANTED
# Notifies a user when they are added to a document
# ---------------------------------------------------------------------------
@receiver(post_save, sender=DocumentPermissionModel)
def notify_access_granted(sender, instance, created, **kwargs):
    if not created:
        return

    try:
        recipient = instance.user
        actor     = instance.document.created_by
        perm_type = instance.permission_type
        document  = instance.document
    except Exception as e:
        logger.warning(f"Access granted notification skipped (FK resolution failed): {e}")
        return

    transaction.on_commit(lambda: _safe_notify(
        recipient=recipient,
        user=actor,
        verb=f"granted you {perm_type} access to",
        target_document=document,
    ))


# ---------------------------------------------------------------------------
# CONNECTION 4 — NEW VERSION & REVIEW REQUEST
# ---------------------------------------------------------------------------
@receiver(post_save, sender=VersionsModel)
def notify_of_new_version(sender, instance, created, **kwargs):
    if not created:
        return

    try:
        doc_owner = instance.document.created_by
        uploader  = instance.created_by
        document  = instance.document
    except Exception as e:
        logger.warning(f"New version notification skipped (FK resolution failed): {e}")
        return

    # Notify owner if someone else uploaded
    if uploader != doc_owner:
        transaction.on_commit(lambda: _safe_notify(
            recipient=doc_owner,
            user=uploader,
            verb="uploaded a new version to",
            target_document=document,
        ))

    # Notify assigned reviewer if one exists
    review = (
        ReviewModel.objects
        .filter(version=instance)
        .order_by("-reviewed_at")
        .first()
    )

    if review and review.reviewer:
        reviewer = review.reviewer  # capture before lambda closes over it

        transaction.on_commit(lambda: _safe_notify(
            recipient=reviewer,
            user=uploader,
            verb="requested a review for",
            target_document=document,
        ))


# ---------------------------------------------------------------------------
# CONNECTION 5 — GLOBAL ROLE ASSIGNED
# ---------------------------------------------------------------------------
@receiver(post_save, sender=UserRole)
def notify_user_role_assigned(sender, instance, created, **kwargs):
    if not created:
        return

    try:
        recipient = instance.user
        actor     = instance.assigned_by or instance.user
        
        # 1. Get the name safely
        raw_name = getattr(instance.role, "role_name", None)
        
        # 2. Convert to string and strip ALL whitespace
        role_name = str(raw_name).strip()
        
        # 3. Fallback if it's still empty or "None"
        if not role_name or role_name.lower() == "none":
            role_name = "a new" 
            
        # 4. Construct clean verb
        verb = f"assigned you the {role_name} role"
        
    except Exception as e:
        logger.warning(f"Role assigned notification skipped: {e}")
        return

    transaction.on_commit(lambda: _safe_notify(
        recipient=recipient,
        user=actor,
        verb=verb,
    ))
    if not created:
        return

    try:
        recipient = instance.user
        actor     = instance.assigned_by or instance.user
        
        # FIX: Safely get role name, default to "a" if empty so grammar works
        role_name = getattr(instance.role, "role_name", None)
        if not role_name or role_name.strip() == "":
            role_name = "a" 
            
        # FIX: Cleaned up verb string
        verb = f"assigned you the {role_name} role"
        
    except Exception as e:
        logger.warning(f"Role assigned notification skipped: {e}")
        return

    transaction.on_commit(lambda: _safe_notify(
        recipient=recipient,
        user=actor,
        verb=verb,
    ))