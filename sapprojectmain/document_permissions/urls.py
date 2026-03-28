from django.urls import path
from .views import (
    CreateDocumentPermissionView,
    GetDocumentPermissionView,
    DeleteDocumentPermissionView,
    GetAllDocumentPermissionsView,
    GetDocumentMembersView,
    RejectDocumentPermissionView,
)

# URL CONFIGURATION FOR DOCUMENT ACCESS CONTROL
urlpatterns = [
    # NOTE: Provides a global overview for administrators or dashboard summaries
    path("", GetAllDocumentPermissionsView.as_view(), name="permission-list"),
    # IMP: The entry point for inviting users or granting new access levels
    path("grant/", CreateDocumentPermissionView.as_view(), name="permission-grant"),
    # NOTE: Retrieves all members currently assigned to a specific document ID
    path(
        "<uuid:doc_id>/members/", GetDocumentMembersView.as_view(), name="doc-members"
    ),
    # SECURITY: Accessing or revoking a specific permission record by its unique ID
    path("<uuid:id>/", GetDocumentPermissionView.as_view(), name="permission-detail"),
    path(
        "<uuid:id>/revoke/",
        DeleteDocumentPermissionView.as_view(),
        name="permission-revoke",
    ),
    # IMP: Allows a user to voluntarily remove their own access from a document
    path(
        "<uuid:doc_id>/resign/",
        RejectDocumentPermissionView.as_view(),
        name="permission-resign",
    ),
]

