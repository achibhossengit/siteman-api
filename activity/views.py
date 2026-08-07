from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from core import status_codes
from core.pagination import StandardPagination
from .filters import ActivityLogFilter
from .models import ActivityLog
from .permissions import ACTIVITY_LOG_PERMISSION_CLASSES, activity_logs_for_user
from .serializers import (
    ActivityLogReviewSerializer,
    ActivityLogSerializer,
)


class ActivityLogViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Company-scoped activity timeline (read + one-way review).

    Global gate: ``view_activitylog`` (list/retrieve), ``change_activitylog``
    (review). Rows are limited to daily_record and site_cash,
    then narrowed by allowed sites and each entity's
    ``view_<model>`` permission.
    """

    serializer_class = ActivityLogSerializer
    queryset = ActivityLog.objects.none()
    permission_classes = ACTIVITY_LOG_PERMISSION_CLASSES
    http_method_names = ["get", "post", "head", "options"]
    filterset_class = ActivityLogFilter
    pagination_class = StandardPagination

    def get_queryset(self):
        return (
            activity_logs_for_user(self.request.user)
            .select_related("actor", "reviewed_by", "site", "labour")
            .order_by("-created_at", "-id")
        )

    @action(detail=False, methods=["post"], url_path="review")
    def review(self, request, *args, **kwargs):
        """Mark one or more logs as reviewed (one-way; skips already reviewed)."""
        serializer = ActivityLogReviewSerializer(data=request.data)
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
        updated = qs.filter(reviewed_at__isnull=True).update(
            reviewed_at=now,
            reviewed_by=request.user,
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
