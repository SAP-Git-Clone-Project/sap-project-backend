from django.contrib import admin
from .models import DocumentPermissionModel

# ADMIN INTERFACE FOR DOCUMENT PERMISSIONS
@admin.register(DocumentPermissionModel)
class DocumentPermissionAdmin(admin.ModelAdmin):
    # NOTE: Defined columns for the permission oversight table
    list_display = (
        "id",
        "get_document_title",
        "user",
        "permission_type",
        "granted_at",
        "created_at",
    )

    # NOTE: Filters and search capabilities for quick access control auditing
    list_filter = ("permission_type", "created_at", "granted_at", "user")
    search_fields = ("user__email", "user__username", "document__title", "document__id")

    # IMP: Use raw_id to prevent browser lag with large User or Document datasets
    raw_id_fields = ("user", "document")

    # SECURITY: System-generated timestamps and IDs must remain immutable
    readonly_fields = ("id", "granted_at", "created_at", "updated_at")

    # NOTE: Grouping fields to improve readability in the detail view
    fieldsets = (
        ("Access Mapping", {"fields": ("id", "document", "user")}),
        ("Privilege Level", {"fields": ("permission_type",)}),
        ("Audit Dates", {"fields": ("granted_at", "created_at", "updated_at")}),
    )

    # NOTE: Displaying the human-readable document title instead of a UUID string
    def get_document_title(self, obj):
        return obj.document.title

    get_document_title.short_description = "Document Title"

    # NOTE: Newest permission grants appear at the top by default
    ordering = ("-created_at",)

# IMP: Ensure staff users have 'view' permissions for both User and Document models