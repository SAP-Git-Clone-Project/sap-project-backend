from django.contrib import admin
from .models import ReviewModel, ReviewStatus


@admin.register(ReviewModel)
class ReviewAdmin(admin.ModelAdmin):
    # NOTE: Table columns for at-a-glance status of document reviews
    list_display = (
        "id",
        "get_document_name",
        "version",
        "reviewer",
        "review_status",
        "reviewed_at",
    )

    # NOTE: Sidebar filters for finding rejected or pending reviews
    list_filter = ("review_status", "reviewed_at")

    # NOTE: Search bar targets specific usernames or version IDs
    search_fields = ("reviewer__username", "version__id", "comments")

    # IMP: ID lookup for related fields to handle high-volume data efficiently
    # SECURITY: Read-only fields to maintain audit integrity of timestamps
    raw_id_fields = ("version", "reviewer")
    readonly_fields = ("id", "reviewed_at")

    ordering = ("-reviewed_at",)

    # NOTE: Helper to display the related document title in the list view
    def get_document_name(self, obj):
        return obj.version.document.title

    get_document_name.short_description = "Document"

    # NOTE: Groups review data into logical sections for the admin interface
    fieldsets = (
        ("Review Target", {"fields": ("id", "version")}),
        (
            "Decision Data",
            {"fields": ("reviewer", "review_status", "comments", "reviewed_at")},
        ),
    )
