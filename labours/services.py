from dataclasses import dataclass
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
from .models import (
    Attendance,
    LabourPayment,
    LabourPaymentType,
    LabourSession,
)

_ZERO = Value(0)
_ZERO_DEC = Value(Decimal("0"))
_DECIMAL = DecimalField(max_digits=20, decimal_places=2)


@dataclass
class SessionSnapshot:
    start_date: object
    end_date: object
    present_days: Decimal
    salary_earnings: int
    extra_earnings: int
    total_payment: int
    total_return: int
    affected_attendance_rows: int
    affected_payment_rows: int

    @property
    def total_earnings(self):
        return self.salary_earnings + self.extra_earnings

    @property
    def payable(self):
        return self.total_earnings + self.total_return - self.total_payment


def _date_filter(*, after=None, start_date=None, end_date=None):
    filters = {}
    if after is not None:
        filters["date__gt"] = after
    if start_date is not None:
        filters["date__gte"] = start_date
    if end_date is not None:
        filters["date__lte"] = end_date
    return filters


def build_session_snapshot(labour, *, after=None, start_date=None, end_date=None):
    """Aggregate the labour's records in the given date window.

    Returns ``None`` when the window contains no records.
    """
    date_filter = _date_filter(after=after, start_date=start_date, end_date=end_date)
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
    ends = [
        d for d in (attendance_agg["latest"], payment_agg["latest"]) if d is not None
    ]

    return SessionSnapshot(
        start_date=min(starts),
        end_date=max(ends),
        present_days=attendance_agg["present_days"] or Decimal("0"),
        salary_earnings=int(attendance_agg["salary_earnings"] or 0),
        extra_earnings=int(attendance_agg["extra_earnings"] or 0),
        total_payment=int(payment_agg["total_payment"] or 0),
        total_return=int(payment_agg["total_return"] or 0),
        affected_attendance_rows=attendance_count,
        affected_payment_rows=payment_count,
    )


def create_labour_session(*, labour, user):
    """Close the labour's open period into a new work session.

    Aggregates every record dated after ``labour.last_session_date`` and
    stores the totals plus effected row count. Sealing is done by the
    ``LabourSession`` post_save signal.
    """
    with transaction.atomic():
        snapshot = build_session_snapshot(labour, after=labour.last_session_date)
        if snapshot is None:
            raise ValidationError(
                "No records exist after the last session; nothing to close.",
                code=status_codes.SESSION_NO_RECORDS,
            )

        try:
            session = LabourSession.objects.create(
                labour=labour,
                start_date=snapshot.start_date,
                end_date=snapshot.end_date,
                present_days=snapshot.present_days,
                salary_earnings=snapshot.salary_earnings,
                extra_earnings=snapshot.extra_earnings,
                total_payment=snapshot.total_payment,
                total_return=snapshot.total_return,
                affected_attendance_rows=snapshot.affected_attendance_rows,
                affected_payment_rows=snapshot.affected_payment_rows,
                company=labour.company,
                created_by=user,
            )
        except IntegrityError:
            raise ValidationError(
                "A work session already exists for this labour today.",
                code=status_codes.RECORD_UNIQUE_CONSTRAINT_VIOLATION,
            )

    return session


def _snapshot_matches_session(snapshot, session):
    return (
        snapshot.start_date == session.start_date
        and snapshot.end_date == session.end_date
        and snapshot.present_days == session.present_days
        and snapshot.salary_earnings == session.salary_earnings
        and snapshot.extra_earnings == session.extra_earnings
        and snapshot.total_payment == session.total_payment
        and snapshot.total_return == session.total_return
        and snapshot.affected_attendance_rows == session.affected_attendance_rows
        and snapshot.affected_payment_rows == session.affected_payment_rows
    )


def delete_labour_session(session):
    """Delete the labour's most recent work session.

    Only allowed when the current records between ``start_date`` and
    ``end_date`` still reproduce the stored session (snapshot match).
    Unsealing is done by the ``LabourSession`` post_delete signal.
    """
    labour = session.labour

    latest = (
        LabourSession.objects.filter(labour=labour)
        .order_by("-created_date", "-id")
        .first()
    )
    if latest is None or latest.pk != session.pk:
        raise ValidationError(
            "Only the most recent work session can be deleted.",
            code=status_codes.SESSION_NOT_LATEST,
        )

    snapshot = build_session_snapshot(
        labour, start_date=session.start_date, end_date=session.end_date
    )
    if snapshot is None or not _snapshot_matches_session(snapshot, session):
        raise ValidationError(
            "Records no longer match this session; deletion is not allowed.",
            code=status_codes.SESSION_SNAPSHOT_MISMATCH,
        )

    session.delete()


def get_running_session(labour):
    """Build the open (unsealed) period preview for a labour.

    Returns session-shaped totals for records after ``last_session_date``,
    plus ``last_session_payable`` (most recent closed session) and
    ``total_payable`` (last + running).
    """
    latest = labour.sessions.order_by("-created_date", "-id").first()
    last_session_date = latest.created_date if latest is not None else None
    snapshot = build_session_snapshot(labour, after=last_session_date)
    if snapshot is None:
        running = {
            "labour": labour.pk,
            "site": labour.current_site_id,
            "start_date": None,
            "end_date": None,
            "present_days": Decimal("0"),
            "salary_earnings": 0,
            "extra_earnings": 0,
            "total_payment": 0,
            "total_return": 0,
            "total_earnings": 0,
            "payable": 0,
            "affected_attendance_rows": 0,
            "affected_payment_rows": 0,
            "company": labour.company_id,
        }
    else:
        running = {
            "labour": labour.pk,
            "site": labour.current_site_id,
            "start_date": snapshot.start_date,
            "end_date": snapshot.end_date,
            "present_days": snapshot.present_days,
            "salary_earnings": snapshot.salary_earnings,
            "extra_earnings": snapshot.extra_earnings,
            "total_payment": snapshot.total_payment,
            "total_return": snapshot.total_return,
            "total_earnings": snapshot.total_earnings,
            "payable": snapshot.payable,
            "affected_attendance_rows": snapshot.affected_attendance_rows,
            "affected_payment_rows": snapshot.affected_payment_rows,
            "company": labour.company_id,
        }

    last_session_payable = latest.payable if latest is not None else 0
    running["last_session_payable"] = last_session_payable
    running["total_payable"] = last_session_payable + running["payable"]
    return running
