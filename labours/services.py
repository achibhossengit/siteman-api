from dataclasses import dataclass, field
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import (
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
from .models import (
    Attendance,
    LabourPayment,
    LabourPaymentType,
    LabourSession,
    LabourSessionDetail,
)

UNCATEGORIZED = "uncategorized"
_ZERO = Value(0)
_ZERO_DEC = Value(Decimal("0"))
_DECIMAL = DecimalField(max_digits=20, decimal_places=2)


@dataclass
class SiteBreakdown:
    site_id: int
    site_name: str
    present_days: Decimal = Decimal("0")
    salary_earnings: int = 0
    extra_earnings: int = 0
    total_payment: int = 0
    total_return: int = 0
    payment_details: dict = field(default_factory=dict)


@dataclass
class SessionSnapshot:
    start_date: object
    end_date: object
    present_days: Decimal
    salary_earnings: int
    extra_earnings: int
    total_payment: int
    total_return: int
    site_breakdowns: list

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


def _get_or_create_breakdown(breakdowns, site_id, site_name):
    if site_id not in breakdowns:
        breakdowns[site_id] = SiteBreakdown(site_id=site_id, site_name=site_name)
    return breakdowns[site_id]


def build_session_snapshot(labour, *, after=None, start_date=None, end_date=None):
    """Aggregate the labour's records in the given date window via SQL GROUP BY.

    Returns ``None`` when the window contains no records.
    """
    date_filter = _date_filter(after=after, start_date=start_date, end_date=end_date)
    attendance_qs = Attendance.objects.filter(labour=labour, **date_filter)
    payment_qs = LabourPayment.objects.filter(labour=labour, **date_filter)

    # present * salary per row, then SUM — done in the database.
    # Min/Max(date) fold into the same GROUP BY so we avoid extra range queries.
    salary_expr = ExpressionWrapper(
        Coalesce(F("present"), _ZERO_DEC) * Coalesce(F("salary"), _ZERO),
        output_field=_DECIMAL,
    )
    attendance_rows = list(
        attendance_qs.values("site_id", "site__name").annotate(
            present_days=Coalesce(Sum(Coalesce(F("present"), _ZERO_DEC)), _ZERO_DEC),
            salary_earnings=Coalesce(Sum(salary_expr), _ZERO_DEC),
            extra_earnings=Coalesce(Sum(Coalesce(F("extra"), _ZERO)), _ZERO),
            earliest=Min("date"),
            latest=Max("date"),
        )
    )

    # Static type/category choices → group once in SQL, assemble JSON in Python.
    payment_rows = list(
        payment_qs.values("site_id", "site__name", "type", "category").annotate(
            total=Sum("amount"),
            earliest=Min("date"),
            latest=Max("date"),
        )
    )

    if not attendance_rows and not payment_rows:
        return None

    starts = []
    ends = []
    breakdowns = {}
    for row in attendance_rows:
        breakdown = _get_or_create_breakdown(
            breakdowns, row["site_id"], row["site__name"]
        )
        breakdown.present_days = row["present_days"] or Decimal("0")
        breakdown.salary_earnings = int(row["salary_earnings"] or 0)
        breakdown.extra_earnings = int(row["extra_earnings"] or 0)
        starts.append(row["earliest"])
        ends.append(row["latest"])

    for row in payment_rows:
        breakdown = _get_or_create_breakdown(
            breakdowns, row["site_id"], row["site__name"]
        )
        amount = int(row["total"] or 0)
        if row["type"] == LabourPaymentType.PAYMENT:
            breakdown.total_payment += amount
        else:
            breakdown.total_return += amount
        bucket = breakdown.payment_details.setdefault(row["type"], {})
        category = row["category"] or UNCATEGORIZED
        bucket[category] = bucket.get(category, 0) + amount
        starts.append(row["earliest"])
        ends.append(row["latest"])

    site_breakdowns = sorted(breakdowns.values(), key=lambda b: b.site_id)
    return SessionSnapshot(
        start_date=min(starts),
        end_date=max(ends),
        present_days=sum((b.present_days for b in site_breakdowns), Decimal("0")),
        salary_earnings=sum(b.salary_earnings for b in site_breakdowns),
        extra_earnings=sum(b.extra_earnings for b in site_breakdowns),
        total_payment=sum(b.total_payment for b in site_breakdowns),
        total_return=sum(b.total_return for b in site_breakdowns),
        site_breakdowns=site_breakdowns,
    )


def create_labour_session(*, labour, user):
    """Close the labour's open period into a new work session.

    Aggregates every record dated after ``labour.last_session_date`` and
    stores the totals plus per-site details. Sealing is done by the
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
                site=labour.current_site,
                start_date=snapshot.start_date,
                end_date=snapshot.end_date,
                present_days=snapshot.present_days,
                salary_earnings=snapshot.salary_earnings,
                extra_earnings=snapshot.extra_earnings,
                total_payment=snapshot.total_payment,
                total_return=snapshot.total_return,
                company=labour.company,
                created_by=user,
            )
        except IntegrityError:
            raise ValidationError(
                "A work session already exists for this labour today.",
                code=status_codes.RECORD_UNIQUE_CONSTRAINT_VIOLATION,
            )

        LabourSessionDetail.objects.bulk_create(
            [
                LabourSessionDetail(
                    session=session,
                    site_id=breakdown.site_id,
                    site_name=breakdown.site_name,
                    present_days=breakdown.present_days,
                    salary_earnings=breakdown.salary_earnings,
                    extra_earnings=breakdown.extra_earnings,
                    total_payment=breakdown.total_payment,
                    total_return=breakdown.total_return,
                    payment_details=breakdown.payment_details,
                    company=labour.company,
                    created_by=user,
                )
                for breakdown in snapshot.site_breakdowns
            ]
        )

    return session


def _snapshot_matches_session(snapshot, session):
    if (
        snapshot.start_date != session.start_date
        or snapshot.end_date != session.end_date
        or snapshot.present_days != session.present_days
        or snapshot.salary_earnings != session.salary_earnings
        or snapshot.extra_earnings != session.extra_earnings
        or snapshot.total_payment != session.total_payment
        or snapshot.total_return != session.total_return
    ):
        return False

    details = {detail.site_id: detail for detail in session.details.all()}
    if set(details) != {b.site_id for b in snapshot.site_breakdowns}:
        return False

    for breakdown in snapshot.site_breakdowns:
        detail = details[breakdown.site_id]
        if (
            breakdown.present_days != detail.present_days
            or breakdown.salary_earnings != detail.salary_earnings
            or breakdown.extra_earnings != detail.extra_earnings
            or breakdown.total_payment != detail.total_payment
            or breakdown.total_return != detail.total_return
            or breakdown.payment_details != detail.payment_details
        ):
            return False
    return True


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
            "company": labour.company_id,
        }

    last_session_payable = latest.payable if latest is not None else 0
    running["last_session_payable"] = last_session_payable
    running["total_payable"] = last_session_payable + running["payable"]
    return running
