"""Site report aggregations (daily / profit)."""

from datetime import timedelta
from decimal import Decimal

from django.db.models import (
    DecimalField,
    ExpressionWrapper,
    F,
    Q,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce

from labours.models import (
    Attendance,
    LabourPayment,
    LabourPaymentType,
)
from .models import SiteCash, SiteCashType

_ZERO = Value(0)
_ZERO_DEC = Value(Decimal("0"))
_DECIMAL = DecimalField(max_digits=20, decimal_places=2)


def _site_cash_balance_through(site, *, through_date):
    """Return straight forward site balance without details."""
    
    sitecash = SiteCash.objects.filter(site=site, date__lte=through_date).aggregate(
        cash_in=Coalesce(
            Sum("amount", filter=Q(type=SiteCashType.DEPOSIT)), _ZERO
        ),
        cash_out=Coalesce(
            Sum(
                "amount",
                filter=Q(type__in=[SiteCashType.WITHDRAWAL, SiteCashType.COST]),
            ),
            _ZERO,
        ),
    )
    payments = LabourPayment.objects.filter(site=site, date__lte=through_date).aggregate(
        payment=Coalesce(
            Sum("amount", filter=Q(type=LabourPaymentType.PAYMENT)), _ZERO
        ),
        returns=Coalesce(Sum("amount", filter=Q(type=LabourPaymentType.RETURN)), _ZERO),
    )

    balance = (
        sitecash["cash_in"]
        - sitecash["cash_out"]
        - payments["payment"]
        + payments["returns"]
    )

    return int(balance)


def build_site_daily_report(site, report_date, *, include_private=False):
    """Aggregate one site's day summary for ``report_date``.
    """
    attendance_qs = Attendance.objects.filter(site=site, date=report_date)
    payment_qs = LabourPayment.objects.filter(site=site, date=report_date)
    cash_qs = SiteCash.objects.filter(site=site, date=report_date)

    salary_expr = ExpressionWrapper(
        Coalesce(F("present"), _ZERO_DEC) * Coalesce(F("salary"), _ZERO),
        output_field=_DECIMAL,
    )
    attendance = attendance_qs.aggregate(
        present_count=Coalesce(Sum(Coalesce(F("present"), _ZERO_DEC)), _ZERO_DEC),
        total_salary=Coalesce(Sum(salary_expr), _ZERO_DEC),
        extra_earnings=Coalesce(Sum(Coalesce(F("extra"), _ZERO)), _ZERO),
    )

    payments = payment_qs.aggregate(
        labour_payment=Coalesce(
            Sum("amount", filter=Q(type=LabourPaymentType.PAYMENT)),
            _ZERO,
        ),
        labour_return=Coalesce(
            Sum("amount", filter=Q(type=LabourPaymentType.RETURN)),
            _ZERO,
        ),
    )

    cash = cash_qs.aggregate(
        deposit=Coalesce(
            Sum("amount", filter=Q(type=SiteCashType.DEPOSIT)), _ZERO
        ),
        withdrawal=Coalesce(
            Sum("amount", filter=Q(type=SiteCashType.WITHDRAWAL)), _ZERO
        ),
        site_cost=Coalesce(
            Sum("amount", filter=Q(type=SiteCashType.COST)), _ZERO
        ),
    )
    
    # labour_return is cash in, not a cost
    total_cost = int((payments["labour_payment"] or 0) + (cash["site_cost"] or 0))
    cash_in = int((cash["deposit"] or 0) + (payments["labour_return"] or 0))
    cash_out = int((cash["withdrawal"] or 0) + total_cost)
    remaining = cash_in - cash_out

    previous_date = report_date - timedelta(days=1)
    previous_balance = _site_cash_balance_through(site, through_date=previous_date)
    balance = previous_balance + remaining

    report = {
        "site": site.pk,
        "date": report_date,
        "present_count": attendance["present_count"] or Decimal("0"),
        "labour_payment": int(payments["labour_payment"] or 0),
        "labour_return": int(payments["labour_return"] or 0),
        "deposit": int(cash["deposit"] or 0),
        "withdrawal": int(cash["withdrawal"] or 0),
        "site_cost": int(cash["site_cost"] or 0),
        "total_cost": total_cost,
        "remaining": remaining,
        "previous_balance": previous_balance,
        "balance": balance,
    }

    if include_private:
        report["total_salary"] = int(attendance["total_salary"] or 0)
        report["extra_earnings"] = int(attendance["extra_earnings"] or 0)
    return report
