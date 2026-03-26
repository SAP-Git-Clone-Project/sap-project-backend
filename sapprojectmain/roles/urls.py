from django.urls import path
from .views import UserRoleAssignmentView, UserRoleDetailView

urlpatterns = [
    # GET: List which users have which roles 
    # POST: Assign a new role to a user
    # URL: /api/users/roles/
    path('', UserRoleAssignmentView.as_view(), name='user-role-list'),

    # GET: Retrieve a specific role assignment
    # DELETE: Revoke a role from a user using the assignment ID
    # URL: /api/users/roles/<uuid:pk>/
    path('<uuid:id>/', UserRoleDetailView.as_view(), name='user-role-detail'),
]