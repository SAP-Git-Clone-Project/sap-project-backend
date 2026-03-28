from django.apps import AppConfig

# CONFIGURATION FOR THE AUDIT LOGGING MODULE
class AuditLogConfig(AppConfig):
    # NOTE: Using BigAutoField to handle large volumes of log entries
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'audit_log'

    def ready(self):
        # IMP: This starts 'listening' for database changes to record in history
        # SECURITY: Ensure all model lifecycle events are intercepted for auditing
        import audit_log.signals

# NOTE: The ready() method ensures signals are connected when the app is loaded
# IMP: Keep this import inside ready() to prevent circular dependency errors