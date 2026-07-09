from django.db.models.signals import post_save
from django.dispatch import receiver

from subscription.models import Subscription
from .models import Company


@receiver(post_save, sender=Company)
def create_initial_subscription(sender, instance, created, **kwargs):
    if created:
        # seed trail subscription from here.
        Subscription.objects.create(company=instance)