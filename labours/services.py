from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import (
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    Max,
    Min,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from rest_framework.exceptions import ValidationError

from core import status_codes
from activity.services import log_created, log_deleted
from .models import DailyRecord, Labour, LabourSession

_ZERO = Value(0)
_ZERO_DEC = Value(Decimal("0"))
_DECIMAL = DecimalField(max_digits=20, decimal_places=2)


def build_site_daily_record_list(*, company_id: int, site_id: int, record_date):
    """Merge this site's labours with that day's daily records.

    Empty rows are only for *active* labours on this site. Inactive or
    transferred labours appear only when they already have a record that day.
    """
    records = list(
        DailyRecord.objects.filter(
            company_id=company_id,
            site_id=site_id,
            date=record_date,
        ).select_related("labour")
    )
    records_by_labour_id = {record.labour_id: record for record in records}

    roster = Labour.objects.filter(
        company_id=company_id,
        current_site_id=site_id,
        is_active=True,
    )
    labours_by_id = {labour.pk: labour for labour in roster}
    for record in records:
        labours_by_id.setdefault(record.labour_id, record.labour)

    return [
        {
            "labour": labour,
            "record": records_by_labour_id.get(labour.pk),
        }
        for labour in sorted(
            labours_by_id.values(),
            key=lambda item: (item.name.lower(), item.pk),
        )
    ]


def get_running_session(labour):
    latest_session = labour.sessions.order_by("-end_date", "-id").first()
    latest_session_payable = latest_session.cumulative_payable if latest_session else 0

    # Records after last_session_date (set by LabourSession post_save signal).
    latest_session_date = labour.last_session_date

    if latest_session_date is not None:
        date_filter = {"date__gt": latest_session_date}
    else:
        date_filter = {}

    qs = DailyRecord.objects.filter(labour=labour, **date_filter)

    wage_expr = ExpressionWrapper(
        Coalesce(F("present"), _ZERO_DEC) * Coalesce(F("wage"), _ZERO),
        output_field=_DECIMAL,
    )
    agg = qs.aggregate(
        present_days=Coalesce(Sum(Coalesce(F("present"), _ZERO_DEC)), _ZERO_DEC),
        salary_earnings=Coalesce(Sum(wage_expr), _ZERO_DEC),
        extra_earnings=Coalesce(Sum(Coalesce(F("extra_earn"), _ZERO)), _ZERO),
        total_fooding_pay=Coalesce(Sum(Coalesce(F("fooding_pay"), _ZERO)), _ZERO),
        total_advance_pay=Coalesce(Sum(Coalesce(F("advance_pay"), _ZERO)), _ZERO),
        total_return=Coalesce(Sum(Coalesce(F("return_amount"), _ZERO)), _ZERO),
        earliest=Min("date"),
        latest=Max("date"),
        row_count=Count("id"),
    )

    row_count = agg["row_count"] or 0
    if row_count == 0:
        return None

    present_days = agg["present_days"] or Decimal("0")
    salary_earnings = int(agg["salary_earnings"] or 0)
    extra_earnings = int(agg["extra_earnings"] or 0)
    total_fooding_pay = int(agg["total_fooding_pay"] or 0)
    total_advance_pay = int(agg["total_advance_pay"] or 0)
    total_return = int(agg["total_return"] or 0)
    total_payment = total_fooding_pay + total_advance_pay
    total_earnings = salary_earnings + extra_earnings
    payable = total_earnings + total_return - total_payment

    return {
        "start_date": agg["earliest"],
        "end_date": agg["latest"],
        "present_days": present_days,
        "salary_earnings": salary_earnings,
        "extra_earnings": extra_earnings,
        "total_fooding_pay": total_fooding_pay,
        "total_advance_pay": total_advance_pay,
        "total_payment": total_payment,
        "total_return": total_return,
        "total_earnings": total_earnings,
        "payable": payable,
        "affected_rows": row_count,
        "previous_payable": latest_session_payable,
        "cumulative_payable": latest_session_payable + payable,
    }


def create_labour_session(*, labour, user):
    """Close the labour's open period into a new work session.

    Aggregates every DailyRecord dated after ``labour.last_session_date`` and
    stores the totals plus affected row count. ``previous_payable`` is the
    prior session's ``cumulative_payable`` (0 if none). Sealing is done by
    the ``LabourSession`` post_save signal.
    """
    with transaction.atomic():
        running = get_running_session(labour)
        if running is None:
            raise ValidationError(
                "No records exist after the last session; nothing to close.",
                code=status_codes.SESSION_NO_RECORDS,
            )

        try:
            session = LabourSession.objects.create(
                labour=labour,
                start_date=running["start_date"],
                end_date=running["end_date"],
                present_days=running["present_days"],
                salary_earnings=running["salary_earnings"],
                extra_earnings=running["extra_earnings"],
                total_fooding_pay=running["total_fooding_pay"],
                total_advance_pay=running["total_advance_pay"],
                total_return=running["total_return"],
                affected_rows=running["affected_rows"],
                previous_payable=running["previous_payable"],
                company=user.company,
            )
        except IntegrityError:
            raise ValidationError(
                "A work session already exists for this labour with the same "
                "start or end date.",
                code=status_codes.RECORD_UNIQUE_CONSTRAINT_VIOLATION,
            )
        log_created(user, session)

    return session


def affected_rows_match(session):
    """True when live DailyRecord count still matches the session snapshot."""
    record_filter = {
        "labour_id": session.labour_id,
        "date__gte": session.start_date,
        "date__lte": session.end_date,
    }
    return DailyRecord.objects.filter(**record_filter).count() == session.affected_rows


def is_latest_labour_session(session):
    """True when ``session`` is the labour's most recent work session."""
    latest = (
        LabourSession.objects.filter(labour_id=session.labour_id)
        .order_by("-end_date", "-id")
        .values_list("pk", flat=True)
        .first()
    )
    return latest == session.pk


def delete_labour_session(session, *, actor):
    """Delete the labour's most recent work session.

    Only allowed when DailyRecord row counts between ``start_date`` and
    ``end_date`` still match the session. Unsealing is done by the
    ``LabourSession`` post_delete signal.
    """
    if not is_latest_labour_session(session):
        raise ValidationError(
            "Only the most recent work session can be deleted.",
            code=status_codes.SESSION_NOT_LATEST,
        )

    if not affected_rows_match(session):
        raise ValidationError(
            "Records no longer match this session; deletion is not allowed.",
            code=status_codes.SESSION_SNAPSHOT_MISMATCH,
        )

    with transaction.atomic():
        log_deleted(actor, session)
        session.delete()
