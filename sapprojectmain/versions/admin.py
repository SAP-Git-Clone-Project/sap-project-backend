from django.contrib import admin
from .models import VersionsModel


@admin.register(VersionsModel)
class VersionsAdmin(admin.ModelAdmin):
    # NOTE: Table columns for tracking document version history and authorship
    list_display = (
        "version_number",
        "get_document_title",
        "created_by",
        "status",
        "is_active",
        "created_at",
    )

    # NOTE: Sidebar filters for active status and approval states
    list_filter = ("status", "is_active", "created_at")

    # NOTE: Search targets document titles, user emails, or file checksums
    # IMP: Content search included for deep text retrieval
    search_fields = ("document__title", "created_by__email", "checksum", "content")

    # NOTE: ID lookups for related fields to prevent slow dropdowns on large datasets
    raw_id_fields = ("document", "parent_version", "created_by")

    # SECURITY: Read-only fields to protect file integrity and metadata history
    readonly_fields = (
        "id",
        "version_number",
        "file_path",
        "file_size",
        "checksum",
        "created_at",
    )

    # NOTE: Helper method to display the document title in the list view
    def get_document_title(self, obj):
        return obj.document.title

    get_document_title.short_description = "Document"

    # NOTE: Logical grouping of version fields for better admin usability
    fieldsets = (
        (
            "Identity & Parentage",
            {"fields": ("id", "document", "parent_version", "created_by")},
        ),
        ("Versioning Logic", {"fields": ("version_number", "status", "is_active")}),
        (
            "Storage Details",
            {"fields": ("file_path", "file_size", "checksum", "content")},
        ),
        ("Timestamps", {"fields": ("created_at",)}),
    )

    ordering = ("-created_at",)
