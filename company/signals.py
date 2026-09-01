from datetime import timedelta

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from subscription.models import Subscription
from .models import Company, CompanyConfig

# Trial snapshot until SystemConfig.trial_plan exists (feature-details F2.10 / F4).
# Near paid_until — trial is a limited-time term, not the Free tier.
TRIAL_OPEN_SITE_LIMIT = 2
TRIAL_ACTIVE_USER_LIMIT = 4
TRIAL_ACTIVE_LABOUR_LIMIT = 30
TRIAL_DURATION_DAYS = 14


@receiver(post_save, sender=Company)
def setup_company_defaults(sender, instance, created, **kwargs):
    # Skip during loaddata (raw=True) so fixtures can supply CompanyConfig.
    if created and not kwargs.get("raw", False):
        CompanyConfig.objects.create(company=instance)
        Subscription.objects.create(
            company=instance,
            open_site_limit=TRIAL_OPEN_SITE_LIMIT,
            active_user_limit=TRIAL_ACTIVE_USER_LIMIT,
            active_labour_limit=TRIAL_ACTIVE_LABOUR_LIMIT,
            paid_until=timezone.localdate() + timedelta(days=TRIAL_DURATION_DAYS),
        )