from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .middleware import get_current_ip
from .models import AuditLogModel
from document_permissions.models import DocumentPermissionModel
from documents.models import DocumentModel
from notifications.models import NotificationModel
from reviews.models import ReviewModel
from user_roles.models import UserRole
from versions.models import VersionsModel

User = get_user_model()


# NOTE: before saving User the old data is stored in a temporary attribute to compare changes after save
@receiver(pre_save, sender=User)
def store_old_user_state(sender, instance, **kwargs):
    if not instance.pk:
        instance._old_is_active = None
        return
    try:
        old_user = User.objects.get(pk=instance.pk)
        instance._old_is_active = old_user.is_active
    except User.DoesNotExist:
        instance._old_is_active = None


@receiver(pre_save, sender=ReviewModel)
def store_old_review_status(sender, instance, **kwargs):
    if not instance.pk:
        instance._old_status = None
        return
    try:
        instance._old_status = ReviewModel.objects.get(pk=instance.pk).review_status
    except ReviewModel.DoesNotExist:
        instance._old_status = None


# NOTE: Log user creation, updates (also ban and activate), and the user deletion
@receiver(post_save, sender=User)
def log_user_changes(sender, instance, created, update_fields, **kwargs):
    # Log if the user is created
    if created:
        action = "create user"
        detail = f"New user registered: {instance.email} (ID: {instance.id})"
    # Log if the user active toggle is changed (ban/activate)
    else:
        old_is_active = getattr(instance, "_old_is_active", None)
        if old_is_active is not None and old_is_active != instance.is_active:
            # Log if the is active is true to say unbanned/reactivated otherwise say banned/deactivated
            if instance.is_active:
                action = "update user"
                detail = f"[BAN TAG] User unbanned/reactivated: {instance.email} (ID: {instance.id})"
            else:
                action = "update user"
                detail = f"[BAN TAG] User banned/deactivated: {instance.email} (ID: {instance.id})"
        # Ignore if last_login is updated
        elif update_fields is None or (
            update_fields and "last_login" not in update_fields
        ):
            action = "update user"
            detail = f"User profile updated for: {instance.email} (ID: {instance.id})"
        # Ignore if any other update is made that isn't related to the user profile
        else:
            return
    # NOTE: Create an audit log entry for the user behavior
    AuditLogModel.objects.create(
        user=instance,
        action_type=action,
        ip_address=get_current_ip() or "0.0.0.0",
        description=detail,
    )


# NOTE: The user deletion is logged
@receiver(post_delete, sender=User)
def log_user_deletion(sender, instance, **kwargs):
    AuditLogModel.objects.create(
        action_type="delete user",
        ip_address=get_current_ip() or "0.0.0.0",
        description=f"User permanently deleted: {instance.email} (ID: {instance.id})",
    )


# NOTE: The user login is logged
@receiver(user_logged_in)
def log_login(sender, user, **kwargs):
    AuditLogModel.objects.create(
        user=user,
        action_type="login",
        ip_address=get_current_ip() or "0.0.0.0",
        description=f"User {user.email} (ID: {user.id}) successfully logged in.",
    )


# NOTE: The user logout is logged
@receiver(user_logged_out)
def log_logout(sender, user, **kwargs):
    if not user:
        return
    AuditLogModel.objects.create(
        user=user,
        action_type="logout",
        ip_address=get_current_ip() or "0.0.0.0",
        description=f"User {user.email} (ID: {user.id}) logged out.",
    )


# NOTE: The document creation and updates are logged
@receiver(post_save, sender=DocumentModel)
def log_doc_activity(sender, instance, created, **kwargs):
    # Form the action type using the created flag and the description verb accordingly
    verb = "created" if created else "updated metadata for"
    action = "create document" if created else "update document"
    AuditLogModel.objects.create(
        user=instance.created_by,
        document=instance,
        action_type=action,
        ip_address=get_current_ip() or "0.0.0.0",
        description=(
            f"User {instance.created_by.email} (ID: {instance.created_by.id}) {verb} "
            f"document: '{instance.title}' (ID: {instance.id})"
        ),
    )


# NOTE: The document deletion is logged in separate signal
@receiver(post_delete, sender=DocumentModel)
def log_doc_deletion(sender, instance, **kwargs):
    AuditLogModel.objects.create(
        action_type="delete document",
        ip_address=get_current_ip() or "0.0.0.0",
        description=f"Document permanently deleted: '{instance.title}' (ID: {instance.id})",
    )


@receiver(post_save, sender=DocumentPermissionModel)
def log_permission_change(sender, instance, created, **kwargs):
    granter = instance.document.created_by
    action_str = "granted" if created else "modified"
    AuditLogModel.objects.create(
        user=granter,
        document=instance.document,
        action_type="update metadata",
        ip_address=get_current_ip() or "0.0.0.0",
        description=(
            f"User {granter.email} (ID: {granter.id}) {action_str} '{instance.permission_type}' "
            f"access to User {instance.user.email} (ID: {instance.user.id}) "
            f"for document: '{instance.document.title}' (ID: {instance.document.id})"
        ),
    )

    # Notifications are centralized here to avoid per-app signal scattering.
    if created:
        transaction.on_commit(
            lambda: NotificationModel.objects.create(
                recipient=instance.user,
                user=granter,
                verb=f"permission granted by admin/owner: {instance.permission_type}",
                target_document=instance.document,
            )
        )


# NOTE: This function automatically runs whenever a document permission is created or updated, it logs the permission grant or modification in the audit log and sends a notification to the user who received the permission.
@receiver(post_delete, sender=DocumentPermissionModel)
def log_permission_revoke(sender, instance, **kwargs):
    try:
        granter = instance.document.created_by
        actor = f"User {granter.email} (ID: {granter.id}) revoked"
        doc_info = (
            f"for document: '{instance.document.title}' (ID: {instance.document.id})"
        )
    except Exception:
        actor = "System revoked"
        doc_info = "— document no longer exists (cascade deletion)"
        granter = None

    AuditLogModel.objects.create(
        user=granter,
        action_type="update metadata",
        ip_address=get_current_ip() or "0.0.0.0",
        description=(
            f"{actor} '{instance.permission_type}' access "
            f"from User {instance.user.email} (ID: {instance.user.id}) "
            f"{doc_info}"
        ),
    )

    if granter:
        transaction.on_commit(
            lambda: NotificationModel.objects.create(
                recipient=instance.user,
                user=granter,
                verb=f"permission revoked by admin/owner: {instance.permission_type}",
                target_document=instance.document,
            )
        )


@receiver(post_save, sender=VersionsModel)
def log_version_activity(sender, instance, created, **kwargs):
    if not created or not instance.created_by:
        return

    AuditLogModel.objects.create(
        user=instance.created_by,
        document=instance.document,
        version=instance,
        action_type="create version",
        ip_address=get_current_ip() or "0.0.0.0",
        description=(
            f"User {instance.created_by.email} (ID: {instance.created_by.id}) uploaded "
            f"version {instance.version_number} (ID: {instance.id}) "
            f"for document: '{instance.document.title}' (ID: {instance.document.id})"
        ),
    )

    # Notify the docuemtn owner if a new version is created not by the owner themselves
    if instance.created_by != instance.document.created_by:
        transaction.on_commit(
            lambda: NotificationModel.objects.create(
                recipient=instance.document.created_by,
                user=instance.created_by,
                verb="uploaded a new version to",
                target_document=instance.document,
            )
        )


@receiver(post_delete, sender=VersionsModel)
def log_version_deletion(sender, instance, **kwargs):
    AuditLogModel.objects.create(
        action_type="delete version",
        ip_address=get_current_ip() or "0.0.0.0",
        description=(
            f"Version {instance.version_number} (ID: {instance.id}) permanently deleted "
            f"from document: '{instance.document.title}' (ID: {instance.document.id})"
        ),
    )


@receiver(post_save, sender=ReviewModel)
def log_and_notify_review_activity(sender, instance, created, **kwargs):
    status_value = (instance.review_status or "").lower()
    if status_value == "approved":
        action = "approve version"
    elif status_value == "rejected":
        action = "reject version"
    else:
        action = None
    # NOTE: Log if review is approved/rejected and reviewer exists
    if action and instance.reviewer:
        AuditLogModel.objects.create(
            user=instance.reviewer,
            document=instance.version.document,
            version=instance.version,
            action_type=action,
            ip_address=get_current_ip() or "0.0.0.0",
            description=(
                f"Reviewer {instance.reviewer.email} (ID: {instance.reviewer.id}) {status_value} "
                f"version {instance.version.version_number} (ID: {instance.version.id}) "
                f"of document: '{instance.version.document.title}'"
            ),
        )

    # If this is a new review being created, stop here.
    if created:
        return

    # NOTE: Notify the version creator if their version review status has changed to approved/rejected and the reviewer exists
    old_status = getattr(instance, "_old_status", None)
    new_status = (instance.review_status or "").upper()
    if old_status != instance.review_status and new_status in ["APPROVED", "REJECTED"]:
        transaction.on_commit(
            lambda: NotificationModel.objects.create(
                recipient=instance.version.created_by,
                user=instance.reviewer,
                verb=f"{new_status.lower()} your version of",
                target_document=instance.version.document,
            )
        )

# NOTE: Function runs whenever a user role is created or updated, in it logs the role and sends notification to the user chosen for this role
@receiver(post_save, sender=UserRole)
def log_user_role_assignment(sender, instance, created, **kwargs):
    actor = instance.assigned_by or instance.user
    action_text = "Role added" if created else "Role changed"
    role_name = instance.role.role_name

    AuditLogModel.objects.create(
        user=instance.assigned_by if instance.assigned_by else None,
        action_type="update user",
        ip_address=get_current_ip() or "0.0.0.0",
        description=(
            f"{action_text}: '{role_name}' for user {instance.user.email} (ID: {instance.user.id}) "
            f"by {actor.email} (ID: {actor.id})"
        ),
    )

    transaction.on_commit(
        lambda: NotificationModel.objects.create(
            recipient=instance.user,
            user=instance.assigned_by,
            verb=f"{action_text.lower()} by admin: {role_name}",
        )
    )


@receiver(post_delete, sender=UserRole)
def log_user_role_revocation(sender, instance, **kwargs):
    actor = instance.assigned_by or instance.user
    role_name = instance.role.role_name
    AuditLogModel.objects.create(
        user=instance.assigned_by if instance.assigned_by else None,
        action_type="update user",
        ip_address=get_current_ip() or "0.0.0.0",
        description=(
            f"Role removed: '{role_name}' from user {instance.user.email} (ID: {instance.user.id}) "
            f"by {actor.email} (ID: {actor.id})"
        ),
    )

    transaction.on_commit(
        lambda: NotificationModel.objects.create(
            recipient=instance.user,
            user=instance.assigned_by,
            verb=f"role removed by admin: {role_name}",
        )
    )
