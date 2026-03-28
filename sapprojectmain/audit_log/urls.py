from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AuditLogViewSet

# NOTE: DefaultRouter handles automatic URL routing for the audit log endpoints
router = DefaultRouter()
router.register(r'logs', AuditLogViewSet, basename='auditlog')

# IMP: All audit log API routes are nested under the router inclusion
urlpatterns = [
    path('', include(router.urls)),
]

# NOTE: This setup provides standard list and retrieve actions for the audit trail
# SECURITY: Ensure that the 'logs/' endpoint is protected by appropriate permissions