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
