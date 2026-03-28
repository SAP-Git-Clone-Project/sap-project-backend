from django.contrib import admin
from .models import AuditLogModel


# ADMIN INTERFACE FOR SYSTEM LOGGING
@admin.register(AuditLogModel)
class AuditLogAdmin(admin.ModelAdmin):
    # NOTE: Summary view columns for high-level audit tracking
    list_display = ("timestamp", "user", "action_type", "document")

    # SECURITY: Dynamically setting all model fields to read-only to prevent tampering
    readonly_fields = [f.name for f in AuditLogModel._meta.get_fields()]

    # IMP: Hard-disable creation to ensure logs only originate from system events
    def has_add_permission(self, request):
        return False

    # SECURITY: Prevent any modifications to existing log data via the UI
    def has_change_permission(self, request, obj=None):
        return False

    # IMP: Disable deletion to maintain a complete and permanent audit trail
    def has_delete_permission(self, request, obj=None):
        return False


# NOTE: The use of list_display ensures quick oversight of the most relevant fields
# IMP: Ensure that the 'document' field in the model is compatible with list_display
