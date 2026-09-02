from rest_framework.permissions import BasePermission
from rest_framework.exceptions import PermissionDenied

from core import status_codes


class HasSitePermissions(BasePermission):
    """
    1. Resolve the site id from the route.
    2. Check the user has access to that site.
    """

    def get_site_id(self, request, view):
        """Nested routes use ``site_pk``; SiteViewSet detail actions use ``pk``."""
        site_id = view.kwargs.get("site_pk")
        if site_id is None:
            site_id = view.kwargs.get("pk")
        return site_id

    def has_permission(self, request, view):
        site_id = self.get_site_id(request, view)

        if site_id is None:
            return False

        site_id = int(site_id)

        # Check if the user has access to the site:
        # - If the user is a company admin, access is always allowed for sites in their company.
        # - Otherwise, require the user to be assigned to the site (via has_site_access).
        # Site permission check totally goes to the has_site_access method in the user model.
        if not request.user.has_site_access(site_id):
            raise PermissionDenied(
                detail="You are not a member of this site.",
                code=status_codes.UNAUTHORIZED_SITE,
            )

        return True
