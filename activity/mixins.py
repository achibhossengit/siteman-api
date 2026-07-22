"""DRF mixin: log change/deletion on perform_update / perform_destroy."""

from .services import log_change, log_deletion, snapshot_instance


class ActivityLogMixin:
    """Wire onto ViewSets that mutate business records via PATCH/DELETE.

    Does not log creates (use ``created_by``). Seal blocked by permissions
    never reaches these methods. Do not use for seal/site-close internals.
    """

    def perform_update(self, serializer):
        instance = serializer.instance
        # Limit snapshot/diff to fields present in the request payload.
        changed_keys = set(serializer.validated_data.keys())
        before = snapshot_instance(instance, fields=changed_keys)
        super().perform_update(serializer)
        instance.refresh_from_db()
        after = snapshot_instance(instance, fields=changed_keys)
        log_change(
            actor=self.request.user,
            company=instance.company,
            instance=instance,
            before=before,
            after=after,
        )

    def perform_destroy(self, instance):
        before = snapshot_instance(instance)
        log_deletion(
            actor=self.request.user,
            company=instance.company,
            instance=instance,
            before=before,
        )
        super().perform_destroy(instance)
