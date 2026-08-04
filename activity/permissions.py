"""Activity log read scoping: company, site membership, entity view perms."""

from .models import ActivityEntityType, ActivityLog

# entity_type → Django view permission for the business model.
ENTITY_VIEW_PERMS: dict[str, str] = {
    ActivityEntityType.USER: "accounts.view_user",
    ActivityEntityType.SITE: "sites.view_site",
    ActivityEntityType.BILLING_CATEGORY: "sites.view_billingcategory",
    ActivityEntityType.SITE_CASH: "sites.view_sitecash",
    ActivityEntityType.PRIVATE_SITE_CASH: "sites.view_privatesitecash",
    ActivityEntityType.LABOUR: "labours.view_labour",
    ActivityEntityType.LABOUR_PAYMENT: "labours.view_labourpayment",
    ActivityEntityType.ATTENDANCE: "labours.view_attendance",
    ActivityEntityType.LABOUR_SESSION: "labours.view_laboursession",
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
