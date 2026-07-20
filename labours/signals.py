from django.db.models import Max
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Attendance, Labour, LabourPayment, LabourSession


def _sync_labour_last_session_date(labour_id):
    latest_date = LabourSession.objects.filter(labour_id=labour_id).aggregate(
        latest=Max("created_date")
    )["latest"]
    Labour.objects.filter(pk=labour_id).update(last_session_date=latest_date)


def _set_records_sealed(labour_id, start_date, end_date, *, sealed):
    """Seal or unseal payment/attendance rows in the session window.

    Uses queryset ``update`` so ``updated_at`` is not bumped.
    """
    record_filter = {
        "labour_id": labour_id,
        "date__gte": start_date,
        "date__lte": end_date,
    }
    Attendance.objects.filter(**record_filter).update(is_sealed=sealed)
    LabourPayment.objects.filter(**record_filter).update(is_sealed=sealed)


@receiver(post_save, sender=LabourSession)
def on_labour_session_save(sender, instance, created, **kwargs):
    if created:
        _set_records_sealed(
            instance.labour_id,
            instance.start_date,
            instance.end_date,
            sealed=True,
        )
    _sync_labour_last_session_date(instance.labour_id)


@receiver(post_delete, sender=LabourSession)
def on_labour_session_delete(sender, instance, **kwargs):
    _set_records_sealed(
        instance.labour_id,
        instance.start_date,
        instance.end_date,
        sealed=False,
    )
    _sync_labour_last_session_date(instance.labour_id)
