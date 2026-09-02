from django.utils import timezone
from rest_framework.permissions import SAFE_METHODS, BasePermission, DjangoModelPermissions
from rest_framework.exceptions import PermissionDenied

from core.exceptions import SubscriptionExpired
from core import status_codes


class DjangoModelPermissionsWithView(DjangoModelPermissions):
    """
    Like DjangoModelPermissions, but GET/HEAD also require view_<model>.

    Stock DjangoModelPermissions leaves GET/HEAD/OPTIONS with an empty
    perms_map, so any authenticated user can list/retrieve without view_*.
    """

    perms_map = {
        "GET": ["%(app_label)s.view_%(model_name)s"],
        "OPTIONS": [],
        "HEAD": ["%(app_label)s.view_%(model_name)s"],
        "POST": ["%(app_label)s.add_%(model_name)s"],
        "PUT": ["%(app_label)s.change_%(model_name)s"],
        "PATCH": ["%(app_label)s.change_%(model_name)s"],
        "DELETE": ["%(app_label)s.delete_%(model_name)s"],
    }


def get_company(request):
    """Cache the tenant company on the request for entitlement checks."""
    if not hasattr(request, "_entitlement_company"):
        user = request.user
        if not user.is_authenticated:
            request._entitlement_company = None
        else:
            request._entitlement_company = getattr(user, "company", None)
    return request._entitlement_company


class ActiveSubscriptionOrReadOnly(BasePermission):
    """
    Reads always pass; writes require paid_until on or after today.
    Expired or missing company => tenant becomes read-only.
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True

        user = request.user
        if not user.is_authenticated:
            return False  # let IsAuthenticated produce the 401

        company = get_company(request)
        if (
            company is None
            or company.paid_until is None
            or company.paid_until < timezone.localdate()
        ):
            raise SubscriptionExpired()
        return True


class IsRecordNotSealed(BasePermission):
    """Object-level: sealed records are immutable."""

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True

        if getattr(obj, "is_sealed", False):
            raise PermissionDenied(
                detail="Sealed records cannot be updated or deleted.",
                code=status_codes.RECORD_SEALED,
            )
        return True


class HasRecordSiteAccess(BasePermission):
    """Object-level: user must have access to the record's site."""

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True

        if not request.user.has_site_access(obj.site_id):
            raise PermissionDenied(
                detail="You are not allowed to update or delete other site records",
                code=status_codes.UNAUTHORIZED_SITE,
            )
        return True
