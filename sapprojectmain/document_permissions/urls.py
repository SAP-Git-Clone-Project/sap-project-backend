from django.urls import path
from .views import (
    CreateDocumentPermissionView,
    GetDocumentPermissionView,
    DeleteDocumentPermissionView,
    GetAllDocumentPermissionsView,
    GetDocumentMembersView,
    RejectDocumentPermissionView,
    CreatePermissionRequestView,
)

# URL CONFIGURATION FOR DOCUMENT ACCESS CONTROL
urlpatterns = [
    # NOTE: Provides a global overview for administrators or dashboard summaries
    path("", GetAllDocumentPermissionsView.as_view(), name="permission-list"),
    # IMP: The entry point for inviting users or granting new access levels
    path("grant/", CreateDocumentPermissionView.as_view(), name="permission-grant"),
    path("request/", CreatePermissionRequestView.as_view(), name="permission-request"),
    # NOTE: Retrieves all members currently assigned to a specific document or version ID.
    # The same GetDocumentMembersView handles both — it already queries by
    # Q(document_id=doc_id) | Q(version_id=doc_id), so passing a version UUID
    # here works without any view changes.
    path(
        "<uuid:doc_id>/members/",
        GetDocumentMembersView.as_view(),
        name="doc-members",
    ),
    # NOTE: Alias used by the frontend's fetchLockedReviewers to check which
    # reviewers have ever been assigned to a specific version. Reuses the same
    # GetDocumentMembersView — the version UUID resolves via version_id on the model.
    path(
        "version/<uuid:doc_id>/reviewers/",
        GetDocumentMembersView.as_view(),
        name="version-reviewers",
    ),
    # SECURITY: Revoking a specific permission record by its unique permission row ID
    path(
        "<uuid:id>/revoke/",
        DeleteDocumentPermissionView.as_view(),
        name="permission-revoke",
    ),
    path("<uuid:id>/", GetDocumentPermissionView.as_view(), name="permission-detail"),
    # IMP: Allows a user to voluntarily remove their own access from a document
    path(
        "<uuid:doc_id>/resign/",
        RejectDocumentPermissionView.as_view(),
        name="permission-resign",
    ),
]