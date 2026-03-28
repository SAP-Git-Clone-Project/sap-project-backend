from django.contrib import admin
from .models import DocumentModel
from versions.models import VersionsModel
from document_permissions.models import DocumentPermissionModel

# --- 1. INLINES ---


class VersionInline(admin.TabularInline):
    # NOTE: Tabular view of document versions for quick history checks
    model = VersionsModel
    extra = 0
    # NOTE: Read-only metadata to prevent manual tampering with version history
    readonly_fields = ("version_number", "status", "is_active", "created_at")
    # SECURITY: Prevent accidental deletion of history records via the admin panel
    can_delete = False


class PermissionInline(admin.TabularInline):
    # NOTE: Tabular view of access permissions directly on the document page
    model = DocumentPermissionModel
    # NOTE: Allows adding a new member without leaving the current page
    extra = 1
    # IMP: Use ID lookup for users to handle large databases efficiently
    raw_id_fields = ("user",)


# --- 2. MAIN DOCUMENT ADMIN ---


@admin.register(DocumentModel)
class DocumentAdmin(admin.ModelAdmin):
    # NOTE: Main table columns for quick overview and identification
    list_display = ("title", "id", "created_by", "created_at", "updated_at")

    # NOTE: Sidebar filters to narrow down by date and owner
    list_filter = ("created_at", "created_by")

    # NOTE: Search bar targets specific document and user details
    search_fields = ("title", "created_by__email", "created_by__username", "id")

    # IMP: ID lookup for creator field to avoid slow dropdowns on high-volume apps
    raw_id_fields = ("created_by",)

    # SECURITY: Locked fields to maintain audit integrity and prevent manual overrides
    readonly_fields = ("id", "created_at", "updated_at")

    # NOTE: Attach related permissions and versions to the document detail view
    inlines = [PermissionInline, VersionInline]

    # NOTE: Organizes the detail page into logical sections for the admin
    fieldsets = (
        ("Core Information", {"fields": ("id", "title", "description", "created_by")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    # NOTE: Newest documents appear at the top of the list by default
    ordering = ("-created_at",)
