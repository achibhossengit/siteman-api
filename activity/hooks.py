"""Helpers for wiring activity logs into viewsets (call explicitly from views)."""

from activity.services import (
    log_created,
    log_created_many,
    log_deleted,
    log_updated,
    snapshot_instance,
    snapshot_user,
)


def _actor(view):
    return view.request.user


def snapshot_for(instance):
    if instance._meta.label_lower == "accounts.user":
        return snapshot_user(instance)
    return snapshot_instance(instance)


def activity_after_create(view, saved):
    """Call after serializer.save() on create (instance or list)."""
    actor = _actor(view)
    if isinstance(saved, (list, tuple)):
        log_created_many(actor, saved)
    else:
        log_created(actor, saved)


def activity_after_update(view, saved, old_snapshot):
    log_updated(actor=_actor(view), instance=saved, old_snapshot=old_snapshot)


def activity_before_destroy(view, instance):
    """Call before instance.delete()."""
    log_deleted(_actor(view), instance)
