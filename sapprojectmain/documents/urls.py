from django.urls import path
from .views import DocumentDeletionDecisionView, DocumentListCreateView, DocumentDetailView, ShareDocumentView, DocumentRequestDeleteView, DocumentListGetAllView

urlpatterns = [
    # NOTE: GET to list all docs and POST to create a new one
    path("", DocumentListCreateView.as_view(), name="document-list-create"),
    path("all/", DocumentListGetAllView.as_view()),
    path("<uuid:id>/request-delete/", DocumentRequestDeleteView.as_view()),
    path("<uuid:id>/deletion-decision/", DocumentDeletionDecisionView.as_view()),
    # NOTE: GET, PUT, and DELETE for a specific document
    path("<uuid:id>/", DocumentDetailView.as_view(), name="document-detail-manage"),
    # IMP: POST to share or update access for this specific document
    path("<uuid:id>/share/", ShareDocumentView.as_view(), name="document-share"),
]
