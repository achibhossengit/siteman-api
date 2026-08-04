from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import (
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    Max,
    Min,
    Q,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from rest_framework.exceptions import ValidationError

from core import status_codes
from activity.services import log_created, log_deleted
from .models import (
    Attendance,
    LabourPayment,
    LabourPaymentType,
    LabourSession,
)

_ZERO = Value(0)
_ZERO_DEC = Value(Decimal("0"))
_DECIMAL = DecimalField(max_digits=20, decimal_places=2)

def get_running_session(labour):
    latest_session = labour.sessions.order_by("-created_date", "-id").first()
    latest_session_payable = latest_session.cumulative_payable if latest_session else 0
    
    # use this to maintain consistency with the old code
    # attendance, labour payment records creation are checked against this date
    # this set by post_save signal of LabourSession model
    latest_session_date = labour.last_session_date
    
    if latest_session_date is not None:
        date_filter = {"date__gt": latest_session_date}
    else:
        date_filter = {}

    attendance_qs = Attendance.objects.filter(labour=labour, **date_filter)
    payment_qs = LabourPayment.objects.filter(labour=labour, **date_filter)

    salary_expr = ExpressionWrapper(
        Coalesce(F("present"), _ZERO_DEC) * Coalesce(F("salary"), _ZERO),
        output_field=_DECIMAL,
    )
    attendance_agg = attendance_qs.aggregate(
        present_days=Coalesce(Sum(Coalesce(F("present"), _ZERO_DEC)), _ZERO_DEC),
        salary_earnings=Coalesce(Sum(salary_expr), _ZERO_DEC),
        extra_earnings=Coalesce(Sum(Coalesce(F("extra"), _ZERO)), _ZERO),
        earliest=Min("date"),
        latest=Max("date"),
        row_count=Count("id"),
    )
    payment_agg = payment_qs.aggregate(
        total_payment=Coalesce(
            Sum("amount", filter=Q(type=LabourPaymentType.PAYMENT)),
            _ZERO,
        ),
        total_return=Coalesce(
            Sum("amount", filter=Q(type=LabourPaymentType.RETURN)),
            _ZERO,
        ),
        earliest=Min("date"),
        latest=Max("date"),
        row_count=Count("id"),
    )

    attendance_count = attendance_agg["row_count"] or 0
    payment_count = payment_agg["row_count"] or 0
    if attendance_count == 0 and payment_count == 0:
        return None

    starts = [
        d for d in (attendance_agg["earliest"], payment_agg["earliest"]) if d is not None
    ]
    ends = [d for d in (attendance_agg["latest"], payment_agg["latest"]) if d is not None]
    present_days = attendance_agg["present_days"] or Decimal("0")
    salary_earnings = int(attendance_agg["salary_earnings"] or 0)
    extra_earnings = int(attendance_agg["extra_earnings"] or 0)
    total_payment = int(payment_agg["total_payment"] or 0)
    total_return = int(payment_agg["total_return"] or 0)
    total_earnings = salary_earnings + extra_earnings
    payable = total_earnings + total_return - total_payment

    running = {
        "start_date": min(starts),
        "end_date": max(ends),
        "present_days": present_days,
        "salary_earnings": salary_earnings,
        "extra_earnings": extra_earnings,
        "total_payment": total_payment,
        "total_return": total_return,
        "total_earnings": total_earnings,
        "payable": payable,
        "affected_attendance_rows": attendance_count,
        "affected_payment_rows": payment_count,
        "previous_payable": latest_session_payable,
        "cumulative_payable": latest_session_payable + payable,
    }
    return running


def create_labour_session(*, labour, user):
    """Close the labour's open period into a new work session.

    Aggregates every record dated after ``labour.last_session_date`` and
    stores the totals plus affected row counts. ``previous_payable`` is
    the prior session's ``cumulative_payable`` (0 if none). Sealing is
    done by the ``LabourSession`` post_save signal.
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
                total_payment=running["total_payment"],
                total_return=running["total_return"],
                affected_attendance_rows=running["affected_attendance_rows"],
                affected_payment_rows=running["affected_payment_rows"],
                previous_payable=running["previous_payable"],
                company=user.company,
            )
        except IntegrityError:
            raise ValidationError(
                "A work session already exists for this labour today.",
                code=status_codes.RECORD_UNIQUE_CONSTRAINT_VIOLATION,
            )
        log_created(user, session)

    return session


def affected_rows_match(session):
    """True when live attendance/payment counts still match the session."""
    record_filter = {
        "labour_id": session.labour_id,
        "date__gte": session.start_date,
        "date__lte": session.end_date,
    }
    attendance_count = Attendance.objects.filter(**record_filter).count()
    payment_count = LabourPayment.objects.filter(**record_filter).count()
    return (
        attendance_count == session.affected_attendance_rows
        and payment_count == session.affected_payment_rows
    )


def is_latest_labour_session(session):
    """True when ``session`` is the labour's most recent work session."""
    latest = (
        LabourSession.objects.filter(labour_id=session.labour_id)
        .order_by("-created_date", "-id")
        .values_list("pk", flat=True)
        .first()
    )
    return latest == session.pk


def delete_labour_session(session, *, actor):
    """Delete the labour's most recent work session.

    Only allowed when attendance/payment row counts between ``start_date``
    and ``end_date`` still match the session. Unsealing is done by the
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