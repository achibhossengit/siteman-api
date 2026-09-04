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

from labours.models import DailyRecord
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
    labour_cash = DailyRecord.objects.filter(site=site, date__lte=through_date).aggregate(
        fooding=Coalesce(Sum(Coalesce(F("fooding_pay"), _ZERO)), _ZERO),
        advance=Coalesce(Sum(Coalesce(F("advance_pay"), _ZERO)), _ZERO),
        returns=Coalesce(Sum(Coalesce(F("return_amount"), _ZERO)), _ZERO),
    )

    balance = (
        sitecash["cash_in"]
        - sitecash["cash_out"]
        - (labour_cash["fooding"] or 0)
        - (labour_cash["advance"] or 0)
        + (labour_cash["returns"] or 0)
    )

    return int(balance)


def aggregate_site_cash_totals(queryset):
    """Sum deposit / withdrawal / cost over a (possibly filtered) SiteCash qs."""
    agg = queryset.aggregate(
        total_deposit=Coalesce(
            Sum("amount", filter=Q(type=SiteCashType.DEPOSIT)), _ZERO
        ),
        total_withdrawal=Coalesce(
            Sum("amount", filter=Q(type=SiteCashType.WITHDRAWAL)), _ZERO
        ),
        total_cost=Coalesce(
            Sum("amount", filter=Q(type=SiteCashType.COST)), _ZERO
        ),
    )
    return {
        "total_deposit": int(agg["total_deposit"] or 0),
        "total_withdrawal": int(agg["total_withdrawal"] or 0),
        "total_cost": int(agg["total_cost"] or 0),
    }


def build_site_daily_report(
    site, start_date=None, end_date=None, *, include_private=False
):
    """Aggregate a site's summary from ``start_date`` through ``end_date``.

    ``end_date`` defaults to ``start_date`` (one day). When both are omitted,
    the report covers all dates. ``previous_balance`` is the running balance
    through the day before ``start_date``, or 0 for an all-time summary.
    """
    if start_date is not None and end_date is None:
        end_date = start_date

    records = DailyRecord.objects.filter(site=site)
    cash_qs = SiteCash.objects.filter(site=site)
    if start_date is not None:
        records = records.filter(date__gte=start_date)
        cash_qs = cash_qs.filter(date__gte=start_date)
    if end_date is not None:
        records = records.filter(date__lte=end_date)
        cash_qs = cash_qs.filter(date__lte=end_date)

    wage_expr = ExpressionWrapper(
        Coalesce(F("present"), _ZERO_DEC) * Coalesce(F("wage"), _ZERO),
        output_field=_DECIMAL,
    )
    labour = records.aggregate(
        present_count=Coalesce(Sum(Coalesce(F("present"), _ZERO_DEC)), _ZERO_DEC),
        total_salary=Coalesce(Sum(wage_expr), _ZERO_DEC),
        extra_earnings=Coalesce(Sum(Coalesce(F("extra_earn"), _ZERO)), _ZERO),
        fooding_pay=Coalesce(Sum(Coalesce(F("fooding_pay"), _ZERO)), _ZERO),
        advance_pay=Coalesce(Sum(Coalesce(F("advance_pay"), _ZERO)), _ZERO),
        labour_return=Coalesce(Sum(Coalesce(F("return_amount"), _ZERO)), _ZERO),
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

    labour_payment = int((labour["fooding_pay"] or 0) + (labour["advance_pay"] or 0))
    labour_return = int(labour["labour_return"] or 0)

    # labour_return is cash in, not a cost
    total_cost = labour_payment + int(cash["site_cost"] or 0)
    cash_in = int((cash["deposit"] or 0) + labour_return)
    cash_out = int((cash["withdrawal"] or 0) + total_cost)
    remaining = cash_in - cash_out

    if start_date is None:
        previous_balance = 0
    else:
        previous_date = start_date - timedelta(days=1)
        previous_balance = _site_cash_balance_through(site, through_date=previous_date)
    balance = previous_balance + remaining

    report = {
        "site": site.pk,
        "present_count": labour["present_count"] or Decimal("0"),
        "labour_payment": labour_payment,
        "labour_return": labour_return,
        "deposit": int(cash["deposit"] or 0),
        "withdrawal": int(cash["withdrawal"] or 0),
        "site_cost": int(cash["site_cost"] or 0),
        "total_cost": total_cost,
        "remaining": remaining,
        "previous_balance": previous_balance,
        "balance": balance,
    }

    if include_private:
        report["total_salary"] = int(labour["total_salary"] or 0)
        report["extra_earnings"] = int(labour["extra_earnings"] or 0)
    return report
