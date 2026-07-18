from django.utils import timezone
from rest_framework.permissions import SAFE_METHODS, BasePermission, DjangoModelPermissions
from rest_framework.exceptions import PermissionDenied

from core.exceptions import SubscriptionExpired
from core import status_codes
from subscription.models import Subscription


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


def get_subscription(request):
    """
    Resolve and cache the tenant subscription on ``request.subscription``.

    Unlocked read used by ActiveSubscriptionOrReadOnly. Later limit checks
    call SubscriptionService.get_locked_subscription(request), which upgrades
    this to a select_for_update row and sets request._subscription_locked.
    """
    if not hasattr(request, "subscription"):
        user = request.user
        if not user.is_authenticated:
            request.subscription = None
        else:
            request.subscription = Subscription.objects.filter(
                company_id=user.company_id
            ).first()
    return request.subscription


class ActiveSubscriptionOrReadOnly(BasePermission):
    """
    Reads always pass; writes require an active subscription.
    Expired or missing subscription => tenant becomes read-only.
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True

        user = request.user
        if not user.is_authenticated:
            return False  # let IsAuthenticated produce the 401

        subscription = get_subscription(request)
        if (
            subscription is None or 
            subscription.paid_until is None or 
            subscription.paid_until < timezone.localdate()
        ):
            raise SubscriptionExpired()
        return True


class RecordUpdateDeletePermissions(BasePermission):
    
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        
        if not request.user.has_site_access(obj.site_id):
            raise PermissionDenied(
                detail="You are not allowed to update or delete other site records",
                code=status_codes.UNAUTHORIZED_SITE,
            )

        if obj.is_sealed:
            raise PermissionDenied(
                detail="Sealed records cannot be updated or deleted.",
                code=status_codes.RECORD_SEALED,
            )
        return True
