from rest_framework.permissions import SAFE_METHODS
from rest_framework.exceptions import PermissionDenied
from core import status_codes
from sites.permissions import HasSitePermissions
from .models import Labour


def get_labour(request, view):
    """Resolve and cache the labour"""

    # 1.check cache
    if hasattr(request, "_cached_labour"):
        return request._cached_labour

    # 2. get labour from db
    labour_pk = view.kwargs.get("labour_pk")
    if not labour_pk or not getattr(request.user, "is_authenticated", False):
        request._cached_labour = None
        return None
    
    labour = (
        Labour.objects.filter(pk=labour_pk, company_id=request.user.company_id)
        .select_related("current_site")
        .first()
    )
    
    # 3. set cache
    request._cached_labour = labour
    return labour


class HasSiteAndLabourPermissions(HasSitePermissions):
    """
    Permission for endpoints nested under:
    1. Checks site permissions first.
    2. Checks labour exists and is active (for non-safe methods).
    """

    def get_site_id(self, request, view):
        labour = get_labour(request, view)
        return labour.current_site_id if labour else None

    def has_permission(self, request, view):
        # 1. Check Site Permissions (Priotize this over labour permissions)
        if not super().has_permission(request, view):
            return False

        # 2. Check Labour Permissions
        labour = get_labour(request, view)
        if not labour:
            return False

        # Only enforce active status for destructive (non-safe) methods
        if not labour.is_active and request.method not in SAFE_METHODS:
            raise PermissionDenied(
                detail="This labour is inactive; no changes can be made.",
                code=status_codes.LABOUR_INACTIVE,
            )

        return True