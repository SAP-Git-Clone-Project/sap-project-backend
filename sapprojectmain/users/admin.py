from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import UserModel


@admin.register(UserModel)
class UserAdmin(BaseUserAdmin):
    # NOTE: Table columns for user management including status and timestamps
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "is_active",
        "is_staff",
        "is_superuser",
        "created_at",
        "updated_at",
    )

    # NOTE: Sidebar filters for account status and activity dates
    list_filter = ("is_active", "is_staff", "is_superuser", "created_at", "updated_at")

    # NOTE: Search bar targets primary identity and contact fields
    search_fields = ("email", "username", "first_name", "last_name")
    ordering = ("-created_at",)

    # SECURITY: System-generated IDs and timestamps remain read-only
    readonly_fields = ("id", "created_at", "updated_at")

    # NOTE: Organizes user data into distinct collapsible sections for the admin
    fieldsets = (
        (
            "Account Identity",
            {
                "fields": (
                    "id",
                    "email",
                    "username",
                    "password",
                    "first_name",
                    "last_name",
                    "avatar",
                )
            },
        ),
        (
            "System Status & Authority",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                )
            },
        ),
        (
            "Security Groups",
            {
                "classes": ("collapse",),
                "fields": ("groups", "user_permissions"),
            },
        ),
        ("Metadata", {"fields": ("created_at", "updated_at")}),
    )

    # NOTE: Provides a side-by-side UI for managing group and permission relationships
    filter_horizontal = ("groups", "user_permissions")

    def save_model(self, request, obj, form, change):
        # NOTE: Ensures passwords are correctly hashed when modified via admin
        if "password" in form.changed_data:
            obj.set_password(obj.password)
        super().save_model(request, obj, form, change)
