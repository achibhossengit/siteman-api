from django.db.models import Max
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Labour, LabourSession


def _sync_labour_last_session_date(labour_id):
    latest_date = LabourSession.objects.filter(labour_id=labour_id).aggregate(
        latest=Max("created_date")
    )["latest"]
    Labour.objects.filter(pk=labour_id).update(last_session_date=latest_date)


@receiver(post_save, sender=LabourSession)
def sync_last_session_date_after_save(sender, instance, **kwargs):
    _sync_labour_last_session_date(instance.labour_id)


@receiver(post_delete, sender=LabourSession)
def sync_last_session_date_after_delete(sender, instance, **kwargs):
    _sync_labour_last_session_date(instance.labour_id)
