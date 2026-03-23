from django.contrib import admin
from .models import UserModel

@admin.register(UserModel)
class UserAdmin(admin.ModelAdmin):
    model = UserModel

    # fields to show
    list_display = (
        "id",
        "email",
        "username",
        "avatar",
        "is_enabled",
        "is_staff",
        "is_superuser",
        "created_at",
        "updated_at",
    )

    list_filter = (
        "is_enabled",
        "is_staff",
        "is_superuser",
        "created_at",
    )

    search_fields = (
        "email",
        "username",
        "id",
    )

    ordering = ("-created_at",)

    # admin show user table config
    fieldsets = (
        ("Main Info", {"fields": ("email", "username", "password", "avatar")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_enabled",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Dates", {"fields": ("created_at", "updated_at")}),
    )

    add_fieldsets = None

    filter_horizontal = ("groups", "user_permissions")
