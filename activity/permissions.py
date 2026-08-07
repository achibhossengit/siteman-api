"""Activity log read scoping: company, site membership, entity view perms."""

from rest_framework.permissions import IsAuthenticated

from core.permissions import (
    ActiveSubscriptionOrReadOnly,
    DjangoModelPermissionsWithView,
)
from .models import ActivityEntityType, ActivityLog

# entity_type → Django view permission for the business model.
# Read API only exposes day-review entity types.
ENTITY_VIEW_PERMS: dict[str, str] = {
    ActivityEntityType.DAILY_RECORD: "labours.view_dailyrecord",
    ActivityEntityType.SITE_CASH: "sites.view_sitecash",
}


def allowed_entity_types(user) -> list[str]:
    return [
        entity_type
        for entity_type, perm in ENTITY_VIEW_PERMS.items()
        if user.has_perm(perm)
    ]


def activity_logs_for_user(user):
    """Company-scoped logs narrowed by site access and entity view perms."""
    if not user.is_authenticated or user.company_id is None:
        return ActivityLog.objects.none()

    qs = ActivityLog.objects.filter(company_id=user.company_id)

    if not user.is_companyadmin:
        site_ids = list(user.sites.values_list("site_id", flat=True))
        qs = qs.filter(site_id__in=site_ids)

    entity_types = allowed_entity_types(user)
    if not entity_types:
        return qs.none()
    return qs.filter(entity_type__in=entity_types)


class ActivityLogPermissions(DjangoModelPermissionsWithView):
    """Map review POST to change_activitylog (not add_)."""

    def has_permission(self, request, view):
        if getattr(view, "action", None) == "review":
            return request.user.has_perm("activity.change_activitylog")
        return super().has_permission(request, view)


ACTIVITY_LOG_PERMISSION_CLASSES = [
    IsAuthenticated,
    ActivityLogPermissions,
    ActiveSubscriptionOrReadOnly,
]
