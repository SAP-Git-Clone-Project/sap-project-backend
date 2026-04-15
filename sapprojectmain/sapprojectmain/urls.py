from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.http import JsonResponse


# Simple home view for API health check
def home(request):
    return JsonResponse(
        {
            "message": "Welcome to the Document Management API",
            "status": "online",
            "version": "1.0.0",
            "auth": {
                "login": "/api/token/",
                "refresh": "/api/token/refresh/",
                "register": "/api/users/register/",
            },
        }
    )


urlpatterns = [
    # --- System & Health ---
    path("", home),
    path("admin/", admin.site.urls),
    # --- Authentication (JWT) ---
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    # --- App-Specific Endpoints ---
    path("api/users/", include("users.urls")),
    path("api/documents/", include("documents.urls")),
    path("api/versions/", include("versions.urls")),  # New: Version management
    path(
        "api/permissions/", include("document_permissions.urls")
    ),  # Renamed for clarity
    path("api/reviews/", include("reviews.urls")),
    path("api/notifications/", include("notifications.urls")),  # New: The Inbox
    path("api/roles/", include("user_roles.urls")),
    # Audit log
    path("api/audit-log/", include("audit_log.urls")),
]
