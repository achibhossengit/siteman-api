from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission


class HasTenantCompany(BasePermission):
    """Require the user to belong to a company; otherwise 404."""

    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False
        if user.company_id is None:
            raise NotFound()
        return True
