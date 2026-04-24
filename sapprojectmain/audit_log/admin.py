from django.contrib import admin
from .models import AuditLogModel


# ADMIN INTERFACE FOR SYSTEM LOGGING

# NOTE: Register function makes the AuditLogModel available in the Django admin interface
@admin.register(AuditLogModel)

# NOTE: AuditLogAdmin defines the admin interface for the AuditLogModel, making it read-only and preventing modifications
class AuditLogAdmin(admin.ModelAdmin):
    # NOTE: The list_display specifies which field to show in the admin list view
    list_display = ("timestamp", "user", "action_type", "document")

    # SECURITY: Dynamically setting all model fields to read-only to prevent tampering
    readonly_fields = [f.name for f in AuditLogModel._meta.get_fields()]

    # IMP: Hard-disable creation to ensure logs only originate from system events
    def has_add_permission(self, request):
        return False

    # SECURITY: Prevent any modifications to existing log data via the UI
    def has_change_permission(self, request, obj=None):
        return False

    # SECURITY: Disable deletion to maintain a complete and permanent audit trail
    def has_delete_permission(self, request, obj=None):
        return False

