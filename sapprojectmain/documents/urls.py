from django.urls import path
from .views import CreateDocumentView, GetDocumentView, UpdateDocumentView, DeleteDocumentView, GetAllDocumentsView

urlpatterns = [
    path("", GetAllDocumentsView.as_view(), name="get_all_documents"),
    path("create/", CreateDocumentView.as_view(), name="create_document"),
    path("<uuid:id>/", GetDocumentView.as_view(), name="get_document"),
    path("<uuid:id>/update/", UpdateDocumentView.as_view(), name="update_document"),
    path("<uuid:id>/delete/", DeleteDocumentView.as_view(), name="delete_document"),
]
