from django.urls import path
from .views import (
    DocumentVersionHandler,
    VersionDetailView,
    VersionDiffView,
    VersionExportView,
    VersionInheritedReviewersView
)

urlpatterns = [
    # 1. Most specific paths FIRST
    path(
        "document/<uuid:id>/",
        DocumentVersionHandler.as_view(),
        name="document-versions",
    ),
    path(
        "<uuid:pk>/export/<str:file_format>/",
        VersionExportView.as_view(),
        name="version-export",
    ),
    path("<uuid:pk>/diff/", VersionDiffView.as_view(), name="version-diff"),
    path("<uuid:pk>/inherited-reviewers/", VersionInheritedReviewersView.as_view(), name="version-inherited-reviewers"),
    # 2. General detail path LAST
    path("<uuid:pk>/", VersionDetailView.as_view(), name="version-detail"),
]
