from rest_framework.permissions import BasePermission, IsAuthenticated, SAFE_METHODS


# Staff or Superuser only
class IsStaffOrSuperUser(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and (request.user.is_staff or request.user.is_superuser)
        )


# Superuser only
class IsSuperUser(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user and request.user.is_authenticated and request.user.is_superuser
        )


# Staff only
class IsStaffUser(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.is_staff


# Authenticated only
class IsAuthenticatedUser(IsAuthenticated):
    pass


# Read-only for everyone, write only for authenticated users
class ReadOnlyOrAuthenticatedWrite(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated


# Owner only (object-level)
class IsOwner(BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj == request.user


# Owner or staff/superuser
class IsOwnerOrStaff(BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj == request.user or request.user.is_staff or request.user.is_superuser


# Read-only for unauthenticated, full access for staff
class StaffFullAccessElseReadOnly(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True

        return request.user and request.user.is_authenticated and request.user.is_staff

# NOTE: Checks if user has the global Administrator role.
class IsSystemAdmin(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.user_roles.filter(role__role_name="administrator").exists()
        )


# NOTE: Checks if global role is Author, Reviewer, or Admin
class CanCreateDocument(BasePermission):
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        allowed = ["administrator", "author", "reviewer"]
        return request.user.user_roles.filter(role__role_name__in=allowed).exists()


# NOTE: Checks the specific document-level permission table
class HasDocumentPermission(BasePermission):

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user.is_authenticated:
            return False

        # IMP: Admin Bypass
        if user.user_roles.filter(role__role_name="administrator").exists():
            return True

        # IMP: Check the specific document permission link
        user_perm = obj.document_permissions.filter(user=user).first()

        if user_perm:
            # NOTE: Owners/Contributors can do anything
            if user_perm.permission_type in ["owner", "contributor"]:
                return True
            # NOTE: Reviewers can view or use the 'approve' action
            if user_perm.permission_type == "reviewer":
                return (
                    request.method in SAFE_METHODS
                    or getattr(view, "action", None) == "approve"
                )

        # NOTE: Default Read-Only
        return request.method in SAFE_METHODS
