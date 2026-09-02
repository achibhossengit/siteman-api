from django.utils import timezone
from subscription.models import Subscription
from sites.models import Site
from accounts.models import User
from core.exceptions import SubscriptionLimitExceededError, SubscriptionExpiredError

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
        except Subscription.DoesNotExist:
            raise SubscriptionExpiredError(f"Company {company.name} has no subscription.")

    @classmethod
    def _validate_limit(cls, *, current_count, limit, resource_name):
        """
        Validate a subscription limit. limit == -1 means unlimited.
        """
        if limit == -1:
            return

        if current_count >= limit:
            raise SubscriptionLimitExceededError()

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
            raise SubscriptionExpiredError()
        return subscription

    @classmethod
    def validate_open_site_limit(cls, company):
        """
        Check whether another site can be created.
        """
        subscription = cls._validate_active_subscription(company)

        current_count = Site.objects.filter(company=company).count()

        cls._validate_limit(
            current_count=current_count,
            limit=subscription.open_site_limit,
            resource_name="sites",
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

    @classmethod
    def validate_active_labour_limit(cls, company):
        """
        Check whether another active labour can be created / reactivated.
        """
        # Local import avoids circular import at app load (labours → core → labours).
        from labours.models import Labour

        subscription = cls._validate_active_subscription(company)

        current_count = Labour.objects.filter(
            company=company,
            is_active=True,
        ).count()

        cls._validate_limit(
            current_count=current_count,
            limit=subscription.active_labour_limit,
            resource_name="active labour",
        )
