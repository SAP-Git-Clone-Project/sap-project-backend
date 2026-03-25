from django.contrib import admin
from .models import Versions


@admin.register(Versions)
class VersionsAdmin(admin.ModelAdmin):
    # What columns to show in the list
    list_display = ("version_number", "document", "status", "is_active", "created_at")

    # What to filter by on the right sidebar
    list_filter = ("status", "is_active", "created_at")

    # Allow searching by Document ID or Content
    search_fields = ("document__id", "content", "checksum")

    # Make these fields read-only so you don't accidentally break the file links
    readonly_fields = (
        "id",
        "version_number",
        "file_path",
        "file_size",
        "checksum",
        "created_at",
    )

    # Organize the form
    fieldsets = (
        ("Identity", {"fields": ("id", "document", "parent_version")}),
        ("Status", {"fields": ("version_number", "status", "is_active")}),
        ("File Data", {"fields": ("file_path", "file_size", "checksum", "content")}),
    )
