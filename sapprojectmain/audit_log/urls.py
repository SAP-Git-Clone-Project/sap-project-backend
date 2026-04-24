from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AuditLogViewSet

# NOTE: DefaultRouter handles automatic URL routing for the audit log endpoints (logs/, logs/<uuid:pk>/, ect.)
router = DefaultRouter()
router.register(r'logs', AuditLogViewSet, basename='auditlog')

# IMP: All audit log API routes are nested under the router inclusion
urlpatterns = [
    path('', include(router.urls)),
]
