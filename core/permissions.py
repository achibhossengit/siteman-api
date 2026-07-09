from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission

from subscription.models import Subscription


class NoSubscription(PermissionDenied):
    default_detail = "Company has no subscription."
    default_code = "no_subscription"


class SubscriptionExpired(PermissionDenied):
    default_detail = "Company subscription is expired or was never activated."
    default_code = "subscription_expired"


def get_subscription(request):
    """Resolve and cache the requesting user's company subscription."""
    if not hasattr(request, "subscription"):
        user = request.user
        if not user.is_authenticated or user.company_id is None:
            request.subscription = None
        else:
            request.subscription = Subscription.objects.filter(
                company_id=user.company_id
            ).first()
    return request.subscription


class HasActiveSubscription(BasePermission):
    """Reads always pass; writes require an active subscription.

    Expired or missing subscription => tenant becomes read-only. System-scope
    users (company_id is None) are exempt — platform permissions gate their
    routes. After this permission runs, views can reuse the cached
    request.subscription (e.g. open-site limit checks).
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True

        user = request.user
        if not user.is_authenticated:
            return False  # let IsAuthenticated produce the 401
        if user.company_id is None:
            return True

        subscription = get_subscription(request)
        if subscription is None:
            raise NoSubscription()
        if (
            subscription.paid_until is None
            or subscription.paid_until < timezone.localdate()
        ):
            raise SubscriptionExpired()
        return True
