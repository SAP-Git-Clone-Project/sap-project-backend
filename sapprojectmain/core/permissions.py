from rest_framework.permissions import BasePermission, IsAuthenticated, SAFE_METHODS
from document_permissions.models import DocumentPermissionModel
from django.db.models import Q

# --- SYSTEM PERMISSIONS (User Management) ---


class IsSuperUser(BasePermission):
    """
    The Global God Mode. Can manage Users AND Documents.
    """

    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated and request.user.is_superuser
        )


class IsStaffUser(BasePermission):
    """
    The User Manager. Can CRUD users but NOT documents.
    """

    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated and request.user.is_staff
        )


class IsStaffOrSuperUser(BasePermission):
    """
    Used for User List and User Toggle views.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_staff or request.user.is_superuser)
        )


class IsAuthenticatedUser(IsAuthenticated):
    """
    Extends standard authentication to also check if the
    user account is currently 'Enabled' in the system.
    """

    def has_permission(self, request, view):
        # 1. First, check if they are logged in at all (The Default Check)
        is_authenticated = super().has_permission(request, view)
        if not is_authenticated:
            return False

        # 2. Second, check if the account is actually Active/Enabled
        # This links directly to your ToggleUserView (Ban/Unban logic)
        return getattr(request.user, "is_active", True)


# --- DOCUMENT PERMISSIONS (Document-Level Management) ---


class HasDocumentPermission(BasePermission):
    """
    General document access.
    Bypasses for Superusers.
    Staff (Admins) are BLOCKED unless they are explicitly added to the document.
    """

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        # 1. Superuser Bypass
        if user.is_superuser:
            return True

        # 2. Check Document Permissions Table
        # Note: Staff are treated as regular users here.
        user_perm = obj.document_permissions.filter(user=user).first()
        if not user_perm:
            return False

        # If they are the Owner (WRITE or DELETE perms usually)
        if user_perm.permission_type in ["WRITE", "DELETE"]:
            return True

        # If they are just a reader/reviewer
        return request.method in SAFE_METHODS


class HasDocumentReadPermission(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        user = request.user

        if user.is_superuser:
            return True

        if hasattr(obj, "created_by") and obj.created_by == user:
            return True

        # Determine if we are looking at a Document or a Version
        doc = None
        target_version = None

        if hasattr(obj, "document_permissions"):  # It's a DocumentModel
            doc = obj
            target_version = None
        elif hasattr(obj, "document"):  # It's a VersionModel
            doc = obj.document
            target_version = obj

        if doc:
            permission_query = Q(user=user)
            
            if target_version:
                # If viewing a version, allow if global OR version-specific
                permission_query &= (Q(version=target_version) | Q(version__isnull=True))
            else:
                # If viewing the document root, only global permissions count
                permission_query &= Q(version__isnull=True)

            return doc.document_permissions.filter(permission_query).exists()

        return False


class HasDocumentApprovePermission(BasePermission):
    """
    Specific check for the 'APPROVE' action on a version/document.
    """

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        return obj.document_permissions.filter(
            user=user, permission_type="APPROVE"
        ).exists()


class HasDocumentDeletePermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        kwargs = getattr(view, "kwargs", {})

        doc_id = (
            request.data.get("document")
            or kwargs.get("id")   # ✅ FIXED
        )

        if not doc_id:
            return False

        return DocumentPermissionModel.objects.filter(
            user=user,
            document_id=doc_id,
            permission_type="DELETE",
        ).exists()

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        return obj.document.document_permissions.filter(
            user=user, permission_type="DELETE"
        ).exists()


class IsReviewerForDocument(BasePermission):
    """
    Permission to allow only users with 'APPROVE' access to
    see or finalize a review.
    """

    def has_permission(self, request, view):
        if not IsAuthenticatedUser().has_permission(request, view):
            return False
        return True

    def has_object_permission(self, request, view, obj):
        # obj here is a ReviewModel instance
        user = request.user

        # Staff/Superusers can review anything
        if user.is_staff or user.is_superuser:
            return True

        if obj.version.document.is_deleted:
            return False

        # Check if a permission record exists for this User + this Document
        # with the specific type 'APPROVE'
        return DocumentPermissionModel.objects.filter(
            document=obj.version.document, user=user, permission_type="APPROVE"
        ).exists()


class HasDocumentWritePermission(BasePermission): 
    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return obj.document_permissions.filter(
            user=user, permission_type="WRITE", version_isnull=True
        ).exists()
