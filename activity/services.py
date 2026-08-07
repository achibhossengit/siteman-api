"""Activity log write helpers: snapshot, diff, and append-only log rows."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.db import transaction

from .models import ActivityAction, ActivityEntityType, ActivityLog

# Fields included in snapshots / diffs per entity (FK as <name>_id).
TRACKED_FIELDS: dict[str, tuple[str, ...]] = {
    ActivityEntityType.USER: (
        "name",
        "phone_number",
        "email",
        "is_active",
        "is_staff",
        "is_superuser",
        "is_companyadmin",
    ),  # groups/sites handled specially in snapshot_user
    ActivityEntityType.SITE: ("name", "is_active", "is_closed"),
    ActivityEntityType.BILLING_CATEGORY: (
        "name",
        # "display_order",
        "is_active",
        "is_done",
        "site_id",
    ),
    ActivityEntityType.SITE_CASH: (
        "type",
        "date",
        "amount",
        "note",
        "billing_id",
        "site_id",
    ),
    ActivityEntityType.PRIVATE_SITE_CASH: (
        "type",
        "date",
        "amount",
        "note",
        "billing_id",
        "site_id",
    ),
    ActivityEntityType.LABOUR: (
        "name",
        "current_site_id",
        "default_attendance",
        "default_salary",
        "default_fooding",
        "is_active",
    ),
    ActivityEntityType.DAILY_RECORD: (
        "date",
        "present",
        "extra_earn",
        "fooding_pay",
        "advance_pay",
        "return_amount",
        "note",
        "labour_id",
        "site_id",
        "billing_id",
    ),
    ActivityEntityType.LABOUR_SESSION: (
        "start_date",
        "end_date",
        "created_date",
        "present_days",
        "salary_earnings",
        "extra_earnings",
        "total_fooding_pay",
        "total_advance_pay",
        "total_return",
        "labour_id",
        "previous_payable",
    ),
}

MODEL_ENTITY_TYPE: dict[str, str] = {
    "accounts.user": ActivityEntityType.USER,
    "sites.site": ActivityEntityType.SITE,
    "sites.billingcategory": ActivityEntityType.BILLING_CATEGORY,
    "sites.sitecash": ActivityEntityType.SITE_CASH,
    "sites.privatesitecash": ActivityEntityType.PRIVATE_SITE_CASH,
    "labours.labour": ActivityEntityType.LABOUR,
    "labours.dailyrecord": ActivityEntityType.DAILY_RECORD,
    "labours.laboursession": ActivityEntityType.LABOUR_SESSION,
}


def entity_type_for(instance) -> str:
    key = f"{instance._meta.app_label}.{instance._meta.model_name}"
    try:
        return MODEL_ENTITY_TYPE[key]
    except KeyError as exc:
        raise ValueError(f"No activity entity type for {key}") from exc


def json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def snapshot_instance(instance, *, extra: dict | None = None) -> dict:
    entity_type = entity_type_for(instance)
    fields = TRACKED_FIELDS[entity_type]
    data = {}
    for name in fields:
        data[name] = json_safe(getattr(instance, name, None))
    if extra:
        data.update(json_safe(extra))
    return data


def diff_snapshots(old: dict, new: dict) -> dict:
    changes = {}
    for key in sorted(set(old) | set(new)):
        old_val = old.get(key)
        new_val = new.get(key)
        if old_val != new_val:
            changes[key] = {"old": old_val, "new": new_val}
    return changes


def resolve_site_id(instance) -> int | None:
    entity_type = entity_type_for(instance)
    if entity_type == ActivityEntityType.SITE:
        return instance.pk
    if entity_type == ActivityEntityType.USER:
        return None
    if entity_type == ActivityEntityType.LABOUR:
        return getattr(instance, "current_site_id", None)
    if entity_type == ActivityEntityType.LABOUR_SESSION:
        labour = getattr(instance, "labour", None)
        return getattr(labour, "current_site_id", None) if labour else None
    return getattr(instance, "site_id", None)


def resolve_labour(instance) -> tuple[int | None, str | None]:
    """Return (labour_id, labour_name) for labour-related entities."""
    entity_type = entity_type_for(instance)
    if entity_type == ActivityEntityType.LABOUR:
        return instance.pk, getattr(instance, "name", None)
    if entity_type in (
        ActivityEntityType.DAILY_RECORD,
        ActivityEntityType.LABOUR_SESSION,
    ):
        labour_id = getattr(instance, "labour_id", None)
        labour = getattr(instance, "labour", None)
        name = getattr(labour, "name", None) if labour is not None else None
        return labour_id, name
    return None, None


def resolve_business_date(instance) -> date | None:
    entity_type = entity_type_for(instance)
    if entity_type == ActivityEntityType.LABOUR_SESSION:
        return getattr(instance, "created_date", None)
    if entity_type in (
        ActivityEntityType.SITE_CASH,
        ActivityEntityType.PRIVATE_SITE_CASH,
        ActivityEntityType.DAILY_RECORD,
    ):
        return getattr(instance, "date", None)
    return None


def resolve_company_id(instance, actor) -> int:
    company_id = getattr(instance, "company_id", None)
    if company_id is not None:
        return company_id
    if actor is not None and getattr(actor, "company_id", None) is not None:
        return actor.company_id
    raise ValueError("Cannot resolve company_id for activity log")


def user_groups_snapshot(user) -> list[str]:
    return sorted(user.groups.values_list("name", flat=True))


def user_sites_snapshot(user) -> list[int]:
    return sorted(user.sites.values_list("site_id", flat=True))


def snapshot_user(user) -> dict:
    data = snapshot_instance(user)
    data["groups"] = user_groups_snapshot(user)
    data["sites"] = user_sites_snapshot(user)
    return data


@transaction.atomic
def log_activity(
    *,
    actor,
    action: str,
    entity_type: str,
    entity_id: int,
    company_id: int,
    site_id: int | None = None,
    labour_id: int | None = None,
    labour_name: str | None = None,
    business_date: date | None = None,
    changes: dict | None = None,
    actor_name: str | None = None,
) -> ActivityLog:
    """Append one activity row. Call inside the same atomic block as the mutation."""
    name = actor_name
    if name is None:
        name = getattr(actor, "name", None) or (
            str(actor) if actor is not None else "System"
        )
    return ActivityLog.objects.create(
        company_id=company_id,
        site_id=site_id,
        labour_id=labour_id,
        labour_name=(labour_name[:255] if labour_name else None),
        actor=actor if getattr(actor, "pk", None) else None,
        actor_name=name[:255],
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        business_date=business_date,
        changes=changes,
    )


def log_created(actor, instance, *, extra_snapshot: dict | None = None) -> ActivityLog:
    entity_type = entity_type_for(instance)
    if entity_type == ActivityEntityType.USER:
        changes = snapshot_user(instance)
    else:
        changes = snapshot_instance(instance, extra=extra_snapshot)
    labour_id, labour_name = resolve_labour(instance)
    return log_activity(
        actor=actor,
        action=ActivityAction.CREATED,
        entity_type=entity_type,
        entity_id=instance.pk,
        company_id=resolve_company_id(instance, actor),
        site_id=resolve_site_id(instance),
        labour_id=labour_id,
        labour_name=labour_name,
        business_date=resolve_business_date(instance),
        changes=changes,
    )


def log_updated(
    actor,
    instance,
    *,
    old_snapshot: dict,
    new_snapshot: dict | None = None,
) -> ActivityLog | None:
    entity_type = entity_type_for(instance)
    if new_snapshot is None:
        if entity_type == ActivityEntityType.USER:
            new_snapshot = snapshot_user(instance)
        else:
            new_snapshot = snapshot_instance(instance)
    changes = diff_snapshots(old_snapshot, new_snapshot)
    if not changes:
        return None
    labour_id, labour_name = resolve_labour(instance)
    return log_activity(
        actor=actor,
        action=ActivityAction.UPDATED,
        entity_type=entity_type,
        entity_id=instance.pk,
        company_id=resolve_company_id(instance, actor),
        site_id=resolve_site_id(instance),
        labour_id=labour_id,
        labour_name=labour_name,
        business_date=resolve_business_date(instance),
        changes=changes,
    )


def log_deleted(actor, instance, *, snapshot: dict | None = None) -> ActivityLog:
    """Log delete using instance state *before* it is removed from the DB."""
    entity_type = entity_type_for(instance)
    if snapshot is None:
        if entity_type == ActivityEntityType.USER:
            snapshot = snapshot_user(instance)
        else:
            snapshot = snapshot_instance(instance)
    labour_id, labour_name = resolve_labour(instance)
    return log_activity(
        actor=actor,
        action=ActivityAction.DELETED,
        entity_type=entity_type,
        entity_id=instance.pk,
        company_id=resolve_company_id(instance, actor),
        site_id=resolve_site_id(instance),
        labour_id=labour_id,
        labour_name=labour_name,
        business_date=resolve_business_date(instance),
        changes=snapshot,
    )


def log_created_many(actor, instances) -> list[ActivityLog]:
    return [log_created(actor, instance) for instance in instances]
