"""Wipe a site's operational books without deleting the site or its labours.

Sealed daily records unwind that labour's work sessions from the first
overlapping session through every later session. Session ``post_delete``
unseals remaining rows in those date windows (including other sites) and
refreshes ``Labour.last_session_date``.
"""

from collections import defaultdict

from django.contrib.admin.models import CHANGE, LogEntry
from django.db import transaction
from django.db.models import Q

from activity.models import ActivityEntityType, ActivityLog
from labours.models import DailyRecord, Labour, LabourSession

from .models import BillingCategory, PrivateSiteCash, Site, SiteCash

_SITE_SCOPED_LOG_TYPES = (
    ActivityEntityType.DAILY_RECORD,
    ActivityEntityType.SITE_CASH,
    ActivityEntityType.PRIVATE_SITE_CASH,
    ActivityEntityType.BILLING_CATEGORY,
)


def session_ids_to_unwind(site):
    """Session PKs to delete so this site's sealed records can be removed.

    For each labour, take the earliest session whose date window covers a
    sealed record on this site, then that session and every later one.
    """
    sealed = DailyRecord.objects.filter(site=site, is_sealed=True).values_list(
        "labour_id", "date"
    )
    dates_by_labour = defaultdict(list)
    for labour_id, record_date in sealed:
        dates_by_labour[labour_id].append(record_date)

    session_ids = []
    for labour_id, dates in dates_by_labour.items():
        sessions = list(
            LabourSession.objects.filter(labour_id=labour_id).order_by(
                "end_date", "id"
            )
        )
        earliest = None
        for session in sessions:
            if any(session.start_date <= day <= session.end_date for day in dates):
                earliest = session
                break
        if earliest is None:
            continue
        session_ids.extend(
            session.pk for session in sessions if session.end_date >= earliest.end_date
        )
    return session_ids


def preview_site_reset(site):
    session_ids = session_ids_to_unwind(site)
    scoped_logs = Q(site=site, entity_type__in=_SITE_SCOPED_LOG_TYPES)
    session_logs = Q(
        entity_type=ActivityEntityType.LABOUR_SESSION,
        entity_id__in=session_ids,
    )
    return {
        "daily_records": DailyRecord.objects.filter(site=site).count(),
        "labour_sessions": len(session_ids),
        "site_cash": SiteCash.objects.filter(site=site).count(),
        "private_site_cash": PrivateSiteCash.objects.filter(site=site).count(),
        "billing_categories": BillingCategory.objects.filter(site=site).count(),
        "activity_logs": ActivityLog.objects.filter(scoped_logs | session_logs).count(),
        "session_ids": session_ids,
    }


def reset_site(site, *, actor):
    """Delete this site's books, related sessions, and matching activity logs.

    Labours, user-site assignments, and the site row are kept. Callers must
    not use the API session-delete helper: snapshots will not match.
    """
    with transaction.atomic():
        site = Site.objects.select_for_update().get(pk=site.pk)
        labour_ids = list(
            DailyRecord.objects.filter(site=site)
            .values_list("labour_id", flat=True)
            .distinct()
        )
        if labour_ids:
            list(Labour.objects.select_for_update().filter(pk__in=labour_ids))

        counts = preview_site_reset(site)
        session_ids = counts.pop("session_ids")

        if session_ids:
            LabourSession.objects.filter(pk__in=session_ids).delete()
            ActivityLog.objects.filter(
                entity_type=ActivityEntityType.LABOUR_SESSION,
                entity_id__in=session_ids,
            ).delete()

        DailyRecord.objects.filter(site=site).delete()
        SiteCash.objects.filter(site=site).delete()
        PrivateSiteCash.objects.filter(site=site).delete()
        BillingCategory.objects.filter(site=site).delete()

        ActivityLog.objects.filter(
            site=site,
            entity_type__in=_SITE_SCOPED_LOG_TYPES,
        ).delete()

        LogEntry.objects.log_actions(
            user_id=actor.pk,
            queryset=[site],
            action_flag=CHANGE,
            change_message=(
                "Reset site operational data: "
                f"{counts['daily_records']} daily records, "
                f"{counts['labour_sessions']} sessions, "
                f"{counts['site_cash']} cash, "
                f"{counts['private_site_cash']} private cash, "
                f"{counts['billing_categories']} billing categories, "
                f"{counts['activity_logs']} activity logs."
            ),
            single_object=True,
        )
        return counts
