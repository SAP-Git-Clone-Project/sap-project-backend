from django.urls import path
from .views import (
    RegisterView,
    LoginView,
    UserDetailView,
    UserListView,
    CurrentUserDetailView,
    LogoutView,
    ToggleUserView,
)

urlpatterns = [
    path("", UserListView.as_view(), name="all-users"),
    path("<uuid:id>/", UserDetailView.as_view(), name="user-detail"),
    path("me/", CurrentUserDetailView.as_view(), name="user-me"),
    path("<uuid:id>/toggle/", ToggleUserView.as_view(), name="user-toggle"),
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
]
