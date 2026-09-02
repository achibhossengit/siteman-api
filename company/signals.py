from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Company, CompanyConfig


@receiver(post_save, sender=Company)
def setup_company_defaults(sender, instance, created, **kwargs):
    # Skip during loaddata (raw=True) so fixtures can supply CompanyConfig.
    if created and not kwargs.get("raw", False):
        CompanyConfig.objects.create(company=instance)
