from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    # NOTE: Configures the default primary key type for the notifications app
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"

    def ready(self):
        # Notification and audit signal handlers are centrally registered
        # from audit_log.signals via AuditLogConfig.ready().
        return