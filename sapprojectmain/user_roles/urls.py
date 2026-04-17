from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import RoleViewSet, UserRoleViewSet, UserRoleManageView

router = DefaultRouter()
router.register(r'roles', RoleViewSet, basename='role')
router.register(r'user-roles', UserRoleViewSet, basename='user-role')

urlpatterns = [
    path("manage/", UserRoleManageView.as_view(), name="user-role-manage"),
    path('', include(router.urls)),
]
