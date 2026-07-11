from datetime import timedelta

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from subscription.models import Subscription
from .models import Company

# Trial snapshot until SystemConfig.trial_plan exists (feature-details F2.10 / F4).
# Near paid_until — trial is a limited-time term, not the Free tier.
TRIAL_OPEN_SITE_LIMIT = 1
TRIAL_ACTIVE_USER_LIMIT = -1
TRIAL_ACTIVE_LABOUR_LIMIT = -1
TRIAL_DURATION_DAYS = 14


@receiver(post_save, sender=Company)
def create_initial_subscription(sender, instance, created, **kwargs):
    if created:
        Subscription.objects.create(
            company=instance,
            open_site_limit=TRIAL_OPEN_SITE_LIMIT,
            active_user_limit=TRIAL_ACTIVE_USER_LIMIT,
            active_labour_limit=TRIAL_ACTIVE_LABOUR_LIMIT,
            paid_until=timezone.localdate() + timedelta(days=TRIAL_DURATION_DAYS),
        )

# Later implemnet: auto-create CompanyConfig with built-in defaults (F3.5) — blocked on CompanyConfig model.