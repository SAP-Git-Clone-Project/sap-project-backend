from django.urls import path
from .views import DocumentVersionHandler, VersionDetailView, VersionDiffView

urlpatterns = [
    # NOTE: GET list of all versions for a document or POST to create a new one
    path(
        "document/<uuid:id>/",
        DocumentVersionHandler.as_view(),
        name="document-versions",
    ),
    # NOTE: GET version metadata or PATCH to update status like approval or rejection
    path("<uuid:pk>/", VersionDetailView.as_view(), name="version-detail"),
    # NOTE: GET to perform a GitHub-style comparison between version iterations
    path("<uuid:pk>/diff/", VersionDiffView.as_view(), name="version-diff"),
]
