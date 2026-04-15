from document_permissions.models import DocumentPermissionModel
from user_roles.models import Role, UserRole


PERMISSION_TO_ROLE = {
    DocumentPermissionModel.PermissionType.READ: Role.RoleName.READER,
    # Co-author access is restricted to global AUTHOR users.
    DocumentPermissionModel.PermissionType.WRITE: Role.RoleName.AUTHOR,
    DocumentPermissionModel.PermissionType.APPROVE: Role.RoleName.REVIEWER,
    DocumentPermissionModel.PermissionType.DELETE: Role.RoleName.AUTHOR,
}


def get_global_roles(user):
    if not user or not user.is_authenticated:
        return set()
    return set(
        UserRole.objects.filter(user=user).values_list("role__role_name", flat=True)
    )


def user_has_global_role(user, role_name):
    return role_name in get_global_roles(user)


def get_document_permissions(user, document, version=None):
    if not user or not user.is_authenticated or document is None:
        return set()

    queryset = DocumentPermissionModel.objects.filter(user=user, document=document)
    if version is not None:
        queryset = queryset.filter(version__in=[version, None])
    else:
        queryset = queryset.filter(version__isnull=True)
    return set(queryset.values_list("permission_type", flat=True))


def get_document_role(user, document, version=None):
    permissions = get_document_permissions(user, document, version=version)
    priority = [
        DocumentPermissionModel.PermissionType.DELETE,
        DocumentPermissionModel.PermissionType.WRITE,
        DocumentPermissionModel.PermissionType.APPROVE,
        DocumentPermissionModel.PermissionType.READ,
    ]
    for permission in priority:
        if permission in permissions:
            return PERMISSION_TO_ROLE.get(permission)
    return None


def can_write_document(user, document):
    permissions = get_document_permissions(user, document)
    return bool(
        DocumentPermissionModel.PermissionType.WRITE in permissions
        or DocumentPermissionModel.PermissionType.DELETE in permissions
    )


def can_review_document(user, document, version=None):
    permissions = get_document_permissions(user, document, version=version)
    return (
        DocumentPermissionModel.PermissionType.APPROVE in permissions
        or DocumentPermissionModel.PermissionType.DELETE in permissions
    )


def can_delete_document(user, document):
    permissions = get_document_permissions(user, document)
    return DocumentPermissionModel.PermissionType.DELETE in permissions
