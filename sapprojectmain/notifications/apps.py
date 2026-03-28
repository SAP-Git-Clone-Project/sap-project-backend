from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    # NOTE: Configures the default primary key type for the notifications app
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"

    def ready(self):
        # IMP: Registers signal handlers to ensure they are active on startup
        import notifications.signals