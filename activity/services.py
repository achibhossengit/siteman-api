"""Activity log write helpers.

Seal / queryset ``.update()`` / site-close side-effects must not call these.
Create for models with ``created_by`` is not logged here.

``changes`` shape::

    {"amount": {"before": 2000, "after": 2500}, "note": {"before": "a", "after": "b"}}

For deletion, every field has ``after: null``.
"""

from datetime import date, datetime
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import Model, QuerySet
from django.db.models.fields.files import FieldFile

from .models import ActivityAction, ActivityLog

# Auto fields / audit noise — never include in snapshots.
_SKIP_FIELDS = frozenset(
    {
        "id",
        "pk",
        "created_at",
        "updated_at",
        "created_by",
        "created_by_id",
        "company",
        "company_id",
        "password",
        "is_sealed",
    }
)


def _json_safe(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Model):
        return value.pk
    if isinstance(value, FieldFile):
        return value.name or None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return str(value)


def resolve_site_id(instance, *, site_id=None):
    """Site id for an activity row.

    Site itself uses its own pk. Labour uses ``current_site_id`` (after update
    that is the destination site when transferring).
    """
    if site_id is not None:
        return site_id
    meta = instance._meta
    if meta.app_label == "sites" and meta.model_name == "site":
        return instance.pk
    resolved = getattr(instance, "site_id", None)
    if resolved is None:
        resolved = getattr(instance, "current_site_id", None)
    if resolved is None:
        raise ValueError(
            f"Cannot resolve site_id for {meta.label}#{getattr(instance, 'pk', None)}"
        )
    return resolved


def snapshot_instance(instance, fields=None):
    """Serialize model field values to a JSON-safe dict.

    FK fields are stored as ``<name>_id`` values. Pass ``fields`` to limit
    keys (e.g. only serializer ``validated_data`` keys).
    """
    data = {}
    for field in instance._meta.concrete_fields:
        name = field.name
        attname = field.attname  # e.g. site_id for FK site
        if name in _SKIP_FIELDS or attname in _SKIP_FIELDS:
            continue
        if fields is not None:
            if name not in fields and attname not in fields:
                continue
        key = attname if field.is_relation and not field.many_to_many else name
        if key in _SKIP_FIELDS:
            continue
        data[key] = _json_safe(getattr(instance, attname))
    return data


def build_changes(before, after=None):
    """Build ``{field: {before, after}}`` for keys that differ (or all if after is None).

    When ``after`` is ``None`` (deletion), every key in ``before`` is included
    with ``after: null``.
    """
    before = before or {}
    if after is None:
        return {
            key: {"before": value, "after": None}
            for key, value in before.items()
        }

    changes = {}
    for key in set(before) | set(after):
        old = before.get(key)
        new = after.get(key)
        if old != new:
            changes[key] = {"before": old, "after": new}
    return changes


def log_change(*, actor, company, instance, before, after, site_id=None):
    """Insert a change log if any field values actually differ."""
    changes = build_changes(before, after)
    if not changes:
        return None
    return ActivityLog.objects.create(
        company=company,
        site_id=resolve_site_id(instance, site_id=site_id),
        actor=actor,
        content_type=ContentType.objects.get_for_model(instance, for_concrete_model=True),
        object_id=instance.pk,
        action_flag=ActivityAction.CHANGE,
        changes=changes,
    )


def log_deletion(*, actor, company, instance, before, object_id=None, site_id=None):
    """Insert a deletion log; each field has ``after: null``.

    Pass ``object_id`` when logging after ``instance.delete()`` (pk is cleared).
    """
    changes = build_changes(before, after=None)
    return ActivityLog.objects.create(
        company=company,
        site_id=resolve_site_id(instance, site_id=site_id),
        actor=actor,
        content_type=ContentType.objects.get_for_model(instance, for_concrete_model=True),
        object_id=object_id if object_id is not None else instance.pk,
        action_flag=ActivityAction.DELETION,
        changes=changes,
    )


def filter_logs_by_viewable_resources(queryset: QuerySet, user) -> QuerySet:
    """Hide logs whose target model the user cannot ``view_*``.

    E.g. no ``sites.view_privatesitecash`` → PrivateSiteCash logs omitted.
    """
    ct_ids = list(queryset.values_list("content_type_id", flat=True).distinct())
    if not ct_ids:
        return queryset.none()

    allowed = []
    for ct in ContentType.objects.filter(pk__in=ct_ids):
        if user.has_perm(f"{ct.app_label}.view_{ct.model}"):
            allowed.append(ct.pk)
    if not allowed:
        return queryset.none()
    return queryset.filter(content_type_id__in=allowed)
