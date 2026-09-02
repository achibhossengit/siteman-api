from django.utils import timezone
from company.models import Company
from sites.models import Site
from accounts.models import User
from core.exceptions import SubscriptionLimitExceededError, SubscriptionExpiredError


class SubscriptionService:
    @classmethod
    def _get_locked_company(cls, company):
        """Lock the company row to prevent concurrent limit checks."""
        return Company.objects.select_for_update().get(pk=company.pk)

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
        Require paid_until >= today (writable entitlement).
        """
        company = cls._get_locked_company(company)
        if (
            company.paid_until is None
            or company.paid_until < timezone.localdate()
        ):
            raise SubscriptionExpiredError()
        return company

    @classmethod
    def validate_site_limit(cls, company):
        """Check whether another site can be created."""
        company = cls._validate_active_subscription(company)

        current_count = Site.objects.filter(company=company).count()

        cls._validate_limit(
            current_count=current_count,
            limit=company.site_limit,
            resource_name="sites",
        )

    @classmethod
    def validate_active_user_limit(cls, company):
        """Check whether another active user can be created."""
        company = cls._validate_active_subscription(company)

        current_count = User.objects.filter(
            company=company,
            is_active=True,
        ).count()

        cls._validate_limit(
            current_count=current_count,
            limit=company.active_user_limit,
            resource_name="active users",
        )

    @classmethod
    def validate_active_labour_limit(cls, company):
        """Check whether another active labour can be created / reactivated."""
        # Local import avoids circular import at app load (labours → core → labours).
        from labours.models import Labour

        company = cls._validate_active_subscription(company)

        current_count = Labour.objects.filter(
            company=company,
            is_active=True,
        ).count()

        cls._validate_limit(
            current_count=current_count,
            limit=company.active_labour_limit,
            resource_name="active labour",
        )
