from django.urls import path
from .views import (
    RegisterView,
    LoginView,
    LogoutView,
    UserListDestroyView,
    UserSearchView,
    UserDetailView,
    CurrentUserDetailView,
    ToggleUserView,
    AdminDeleteUserView,
    UserAdminToggleView,
)

urlpatterns = [
    # NOTE: POST to register a new account and POST to login or logout
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    # NOTE: GET to retrieve current authenticated user profile data
    path("me/", CurrentUserDetailView.as_view(), name="user-me"),
    # NOTE: GET for user discovery using search keywords for invitations
    path("search/", UserSearchView.as_view(), name="user-search"),
    # NOTE: GET to list all users for administrative overview
    # Now supports Pagination and full info
    path("", UserListDestroyView.as_view(), name="all-users"),
    # NOTE: GET, PUT, or DELETE for specific user management by UUID
    # Now includes the hierarchical delete logic (Admin can't del Admin, etc.)
    path("<uuid:id>/", UserDetailView.as_view(), name="user-detail"),
    # NOTE: POST to toggle user active status for account suspension
    path("<uuid:id>/toggle/", ToggleUserView.as_view(), name="user-toggle"),
    # NOTE: DELETE only — admin-guarded user termination with password confirmation
    path(
        "<uuid:id>/admin-delete/",
        AdminDeleteUserView.as_view(),
        name="admin-delete-user",
    ),
    # NOTE: POST to toggle user admin status for role management
    path(
        "<uuid:id>/toggle-admin/", 
        UserAdminToggleView.as_view(), 
        name="user-toggle-admin"
    ),
]
