from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission

from core import status_codes
from .models import Labour


def get_labour(request, view):
    """Resolve and cache the nested labour (company-scoped)."""
    if hasattr(request, "_cached_labour"):
        return request._cached_labour

    labour_pk = view.kwargs.get("labour_pk")
    if not labour_pk or not getattr(request.user, "is_authenticated", False):
        request._cached_labour = None
        return None

    labour = (
        Labour.objects.filter(pk=labour_pk, company_id=request.user.company_id)
        .select_related("current_site")
        .first()
    )
    request._cached_labour = labour
    return labour


class LabourSitePermissions(BasePermission):
    """
    Nested under ``labour_pk``.

    - List/create: member of labour.current_site; writes also require labour +
      current site active.
    - Object writes (PATCH/DELETE): member of payment.site (not just current site).
    """

    message = "You are not a member of this labour's current site."

    def has_permission(self, request, view):
        labour = get_labour(request, view)
        if labour is None:
            return False

        site = labour.current_site
        if site is None:
            return False

        if not request.user.is_site_member(site.id):
            return False

        if request.method in SAFE_METHODS:
            return True

        if not labour.is_active:
            raise PermissionDenied(
                detail="This labour is inactive; no changes can be made.",
                code=status_codes.LABOUR_INACTIVE,
            )
        if not site.is_active:
            raise PermissionDenied(
                detail="This labour's current site is inactive; no changes can be made.",
                code=status_codes.SITE_INACTIVE,
            )
        return True

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        
        site = obj.site
        if not request.user.is_site_member(site.id):
            raise PermissionDenied(
                detail="You are not a member of this payment's site.",
                code=status_codes.SITE_MEMBER_REQUIRED,
            )
            
        return True
