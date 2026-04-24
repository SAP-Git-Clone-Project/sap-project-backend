from django.apps import AppConfig


# CONFIGURATION FOR THE AUDIT LOGGING MODULE
class AuditLogConfig(AppConfig):
    # NOTE: Using BigAutoField to handle large volumes of log entries
    default_auto_field = "django.db.models.BigAutoField"
    name = "audit_log"

    # NOTE: The ready() method ensures signals are connected when the app is loaded and starts listening for database changes to log them
    def ready(self):
        # NOTE: Activate signal handlers to listen for changes
        import audit_log.signals