from rest_framework.permissions import BasePermission
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


class HasLabourCurrentSiteAccess(HasSitePermissions):
    """
    Nested under ``/labours/<labour_pk>/...``.

    - Resolve labour (company-scoped).
    - Unassigned labour: companyadmin only.
    - Otherwise: user must have access to labour.current_site
      (and site must be active for unsafe methods).
    """

    def get_site_id(self, request, view):
        labour = get_labour(request, view)
        return labour.current_site_id if labour else None

    def has_permission(self, request, view):
        labour = get_labour(request, view)
        if not labour:
            return False

        if labour.current_site_id is None:
            if not request.user.is_companyadmin:
                raise PermissionDenied(
                    detail="This labour is not assigned to a site.",
                    code=status_codes.LABOUR_UNASSIGNED,
                )
            return True

        return super().has_permission(request, view)


class IsLabourActive(BasePermission):
    """Block writes when the nested labour is inactive. Use for create."""

    def has_permission(self, request, view):
        labour = get_labour(request, view)
        if not labour:
            return False

        if not labour.is_active:
            raise PermissionDenied(
                detail="This labour is inactive; no changes can be made.",
                code=status_codes.LABOUR_INACTIVE,
            )
        return True
