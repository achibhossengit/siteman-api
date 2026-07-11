from django.core.exceptions import ValidationError
from django.utils import timezone

from subscription.models import Subscription
from sites.models import Site
from accounts.models import User


class SubscriptionService:
    @classmethod
    def _get_locked_subscription(cls, company):
        """
        Lock the subscription row to prevent concurrent limit checks.
        """
        try:
            return (
                Subscription.objects
                .select_for_update()
                .select_related("company")
                .get(company=company)
            )
        except Subscription.DoesNotExist as exc:
            raise ValidationError(
                "Company has no subscription.",
                code="no_subscription",
            ) from exc

    @classmethod
    def _validate_limit(cls, *, current_count, limit, resource_name):
        """
        Validate a subscription limit. limit == -1 means unlimited.
        """
        if limit == -1:
            return

        if current_count >= limit:
            raise ValidationError(
                (
                    f"{resource_name.capitalize()} subscription limit is exceeded; "
                    "upgrade your plan."
                ),
                code="subscription_limit_exceeded",
            )

    @classmethod
    def _validate_active_subscription(cls, company):
        """
        Require a subscription with paid_until >= today (writable entitlement).
        """
        subscription = cls._get_locked_subscription(company)
        if (
            subscription.paid_until is None
            or subscription.paid_until < timezone.localdate()
        ):
            raise ValidationError(
                "Company subscription is expired!",
                code="subscription_expired",
            )
        return subscription

    @classmethod
    def validate_open_site_limit(cls, company):
        """
        Check whether another open site can be created / reopened.
        """
        subscription = cls._validate_active_subscription(company)

        current_count = Site.objects.filter(
            company=company,
            is_closed=False,
        ).count()

        cls._validate_limit(
            current_count=current_count,
            limit=subscription.open_site_limit,
            resource_name="open sites",
        )

    @classmethod
    def validate_active_user_limit(cls, company):
        """
        Check whether another active user can be created.
        """
        subscription = cls._validate_active_subscription(company)

        current_count = User.objects.filter(
            company=company,
            is_active=True,
        ).count()

        cls._validate_limit(
            current_count=current_count,
            limit=subscription.active_user_limit,
            resource_name="active users",
        )
