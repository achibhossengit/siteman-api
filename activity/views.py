from django.db import transaction
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from core import status_codes
from .filters import ActivityLogFilter
from .models import ActivityLog
from .pagination import ActivityLogPagination
from .permissions import ACTIVITY_LOG_PERMISSION_CLASSES, activity_logs_for_user
from .serializers import (
    ActivityLogBulkReviewSerializer,
    ActivityLogReviewSerializer,
    ActivityLogSerializer,
)

_UNPAGINATED_REQUIRED_PARAMS = ("site", "business_date", "entity_type")


class ActivityLogViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Company-scoped activity timeline (read + one-way review).

    Global gate: ``view_activitylog`` (list/retrieve), ``change_activitylog``
    (review / review-bulk). Rows are limited to daily_record and site_cash,
    then narrowed by allowed sites and each entity's
    ``view_<model>`` permission.

    Pass ``paginate=false`` with ``site``, ``business_date``, and
    ``entity_type`` to return the full filtered list (day-review screens).
    """

    serializer_class = ActivityLogSerializer
    queryset = ActivityLog.objects.none()
    permission_classes = ACTIVITY_LOG_PERMISSION_CLASSES
    http_method_names = ["get", "post", "patch", "head", "options"]
    filterset_class = ActivityLogFilter
    pagination_class = ActivityLogPagination

    def get_queryset(self):
        return (
            activity_logs_for_user(self.request.user)
            .select_related("actor", "reviewed_by", "site", "labour")
            .order_by("-created_at", "-id")
        )

    def paginate_queryset(self, queryset):
        paginate = self.request.query_params.get("paginate", "true").lower()
        if paginate in ("0", "false", "no"):
            missing = [
                name
                for name in _UNPAGINATED_REQUIRED_PARAMS
                if not self.request.query_params.get(name)
            ]
            if missing:
                raise ValidationError(
                    {
                        "paginate": (
                            "paginate=false requires site, business_date, "
                            "and entity_type filters."
                        ),
                        "missing": missing,
                    },
                    code=status_codes.ACTIVITY_UNPAGINATED_FILTERS_REQUIRED,
                )
            return None
        return super().paginate_queryset(queryset)

    @action(detail=True, methods=["patch"], url_path="review")
    @transaction.atomic
    def review(self, request, *args, **kwargs):
        """Mark a log as reviewed (one-way; cannot undo)."""
        instance = self.get_object()
        if instance.reviewed_at is not None:
            raise ValidationError(
                "This activity log has already been reviewed.",
                code=status_codes.ACTIVITY_ALREADY_REVIEWED,
            )

        serializer = ActivityLogReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = serializer.validated_data.get("review_note") or None
        if note == "":
            note = None

        instance.reviewed_at = timezone.now()
        instance.reviewed_by = request.user
        instance.review_note = note
        instance.save(
            update_fields=["reviewed_at", "reviewed_by", "review_note"]
        )
        return Response(
            ActivityLogSerializer(instance).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="review-bulk")
    @transaction.atomic
    def review_bulk(self, request, *args, **kwargs):
        """Mark many logs as reviewed (one-way; no note)."""
        serializer = ActivityLogBulkReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["ids"]

        qs = self.get_queryset().filter(pk__in=ids)
        found_ids = set(qs.values_list("pk", flat=True))
        missing = [pk for pk in ids if pk not in found_ids]
        if missing:
            raise ValidationError(
                {
                    "ids": (
                        "One or more activity logs were not found or "
                        "are outside your access."
                    ),
                    "missing": missing,
                },
                code=status_codes.INVALID,
            )

        now = timezone.now()
        to_review = qs.filter(reviewed_at__isnull=True)
        updated = to_review.update(
            reviewed_at=now,
            reviewed_by=request.user,
            review_note=None,
        )
        reviewed = (
            self.get_queryset()
            .filter(pk__in=ids)
            .order_by("-created_at", "-id")
        )
        return Response(
            {
                "updated": updated,
                "results": ActivityLogSerializer(reviewed, many=True).data,
            },
            status=status.HTTP_200_OK,
        )
