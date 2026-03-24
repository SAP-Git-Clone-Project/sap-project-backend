from django.urls import path
from .views import CreateDocumentView, GetDocumentView, UpdateDocumentView, DeleteDocumentView

urlpatterns = [
    path("documents/create", CreateDocumentView.as_view(), name="create_document"),
    path("documents/<uuid:id>", GetDocumentView.as_view(), name="get_document"),
    path("documents/<uuid:id>/update", UpdateDocumentView.as_view(), name="update_document"),
    path("documents/<uuid:id>/delete", DeleteDocumentView.as_view(), name="delete_document"),
]
