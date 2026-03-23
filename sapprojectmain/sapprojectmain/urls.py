from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.http import JsonResponse


def home(request):
    return JsonResponse(
        {
            "message": "Welcome to SAP Project API",
            "status": "running",
            "endpoints": {
                "register": "/api/users/register/",
                "login": "/api/token/",
                "refresh": "/api/token/refresh/",
            },
        }
    )


urlpatterns = [
    path("", home),

    path("admin/", admin.site.urls),

    # users app
    path("api/users/", include("users.urls")),
    
    # JWT auth
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
]
