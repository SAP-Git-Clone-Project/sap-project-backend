from django.db.models.signals import post_save, post_delete
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver
from django.contrib.auth import get_user_model

# Direct Imports
from .models import AuditLogModel
from documents.models import DocumentModel
from document_permissions.models import DocumentPermissionModel
from versions.models import VersionsModel
from reviews.models import ReviewModel

# NOTE: Utilizing custom middleware helper to capture request-bound IP addresses
from .middleware import get_current_ip

User = get_user_model()

# --- 1. AUTH & USER LOGS ---


@receiver(post_save, sender=User)
def log_user_changes(sender, instance, created, update_fields, **kwargs):
    if created:
        action = "create user"
        detail = f"New user registered: {instance.email} (ID: {instance.id})"
    elif update_fields and update_fields != frozenset({'last_login'}):
        action = "update user"
        detail = f"User profile updated for: {instance.email} (ID: {instance.id})"
    else:
        return

    # SECURITY: Logging account lifecycle events for identity management oversight
    AuditLogModel.objects.create(
        user=instance,
        action_type=action,
        ip_address=get_current_ip(),
        description=detail,
    )


@receiver(user_logged_in)
def log_login(sender, user, **kwargs):
    # SECURITY: Tracking successful login events with source IP verification
    AuditLogModel.objects.create(
        user=user,
        action_type="login",
        ip_address=get_current_ip(),
        description=f"User {user.email} (ID: {user.id}) successfully logged in.",
    )


@receiver(user_logged_out)
def log_logout(sender, user, **kwargs):
    # NOTE: Capture logout events; user may be None in some session expiry edge cases
    if user:
        AuditLogModel.objects.create(
            user=user,
            action_type="logout",
            ip_address=get_current_ip(),
            description=f"User {user.email} (ID: {user.id}) logged out.",
        )


# --- 2. DOCUMENT LOGS ---


@receiver(post_save, sender=DocumentModel)
def log_doc_activity(sender, instance, created, **kwargs):
    verb = "created" if created else "updated metadata for"
    action = "create document" if created else "update document"

    # IMP: Logging document ownership and metadata modifications
    AuditLogModel.objects.create(
        user=instance.created_by,
        document=instance,
        action_type=action,
        ip_address=get_current_ip(),
        description=(
            f"User {instance.created_by.email} (ID: {instance.created_by.id}) {verb} "
            f"document: '{instance.title}' (ID: {instance.id})"
        ),
    )


@receiver(post_delete, sender=DocumentModel)
def log_doc_deletion(sender, instance, **kwargs):
    # SECURITY: Critical log entry for permanent data removal from the system
    AuditLogModel.objects.create(
        action_type="delete document",
        ip_address=get_current_ip(),
        description=f"Document permanently deleted: '{instance.title}' (ID: {instance.id})",
    )


# --- 3. PERMISSION LOGS ---


@receiver(post_save, sender=DocumentPermissionModel)
def log_permission_change(sender, instance, created, **kwargs):
    granter = instance.document.created_by
    action_str = "granted" if created else "modified"

    # SECURITY: Monitoring access control changes to prevent unauthorized permission escalation
    AuditLogModel.objects.create(
        user=granter,
        document=instance.document,
        action_type="update metadata",
        ip_address=get_current_ip(),
        description=(
            f"User {granter.email} (ID: {granter.id}) {action_str} '{instance.permission_type}' "
            f"access to User {instance.user.email} (ID: {instance.user.id}) "
            f"for document: '{instance.document.title}' (ID: {instance.document.id})"
        ),
    )


# --- 4. VERSION LOGS ---


@receiver(post_save, sender=VersionsModel)
def log_version_activity(sender, instance, created, **kwargs):
    if created:
        if not instance.created_by:
            return

        # IMP: Tracking the upload of new physical files/content iterations
        AuditLogModel.objects.create(
            user=instance.created_by,
            document=instance.document,
            version=instance,
            action_type="create version",
            ip_address=get_current_ip(),
            description=(
                f"User {instance.created_by.email} (ID: {instance.created_by.id}) uploaded "
                f"version {instance.version_number} (ID: {instance.id}) "
                f"for document: '{instance.document.title}' (ID: {instance.document.id})"
            ),
        )


# --- 5. REVIEW LOGS ---


@receiver(post_save, sender=ReviewModel)
def log_review_activity(sender, instance, created, **kwargs):
    # NOTE: Selective logging only for terminal review states (approved/rejected)
    if instance.review_status == "approved":
        action = "approve version"
    elif instance.review_status == "rejected":
        action = "reject version"
    else:
        return
    
    if not instance.reviewer:
        return

    # IMP: Documenting the formal approval/rejection workflow for audit compliance
    AuditLogModel.objects.create(
        user=instance.reviewer,
        document=instance.version.document,
        version=instance.version,
        action_type=action,
        ip_address=get_current_ip(),
        description=(
            f"Reviewer {instance.reviewer.email} (ID: {instance.reviewer.id}) {instance.review_status} "
            f"version {instance.version.version_number} (ID: {instance.version.id}) "
            f"of document: '{instance.version.document.title}'"
        ),
    )
