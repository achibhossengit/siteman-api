from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Site, SiteConfig


@receiver(post_save, sender=Site)
def create_site_config(sender, instance, created, **kwargs):
    if created:
        SiteConfig.objects.create(company=instance.company, site=instance)