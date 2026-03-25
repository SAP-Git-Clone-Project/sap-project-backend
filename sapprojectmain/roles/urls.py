from django.urls import path
from .views import UserRoleAssignmentView, UserRoleDetailView

urlpatterns = [
    # GET: List which users have which roles 
    # POST: Assign a new role to a user
    # URL: /api/users/roles/
    path('roles/', UserRoleAssignmentView.as_view(), name='user-role-list-create'),

    # DELETE: Revoke a role from a user using the assignment ID
    # URL: /api/users/roles/<uuid:pk>/
    path('roles/<uuid:id>/', UserRoleDetailView.as_view(), name='user-role-detail-delete'),
]