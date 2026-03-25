from django.urls import path
from .views import CreateDocumentPermissionView, GetDocumentPermissionView, DeleteDocumentPermissionView, GetAllDocumentPermissionsView

urlpatterns = [
    path("", GetAllDocumentPermissionsView.as_view(), name="get_all_document_permissions"),
    path("create/", CreateDocumentPermissionView.as_view(), name="create_document_permission"),
    path("<uuid:id>/", GetDocumentPermissionView.as_view(), name="get_document_permission"),
    path("<uuid:id>/delete/", DeleteDocumentPermissionView.as_view(), name="delete_document_permission"),
]
