from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.exceptions import PermissionDenied

from core import status_codes
from .models import Site

class HasSitePermissions(BasePermission):
    """
    1. Check site exists.
    2. Check user has access to the site.
    3. Check site is active.
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

        if request.method in SAFE_METHODS:
            return True

        site = Site.objects.get(company_id=request.user.company_id, id=site_id)
        if not site.is_active:
            raise PermissionDenied(
                detail="This site is inactive; no changes can be made.",
                code=status_codes.SITE_INACTIVE,
            )

        return True
