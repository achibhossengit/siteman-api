from django.utils import timezone
from rest_framework.permissions import SAFE_METHODS, BasePermission

from core.exceptions import SubscriptionExpired
from subscription.models import Subscription

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
