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
from .permissions import activity_logs_for_user
from .serializers import ActivityLogReviewSerializer, ActivityLogSerializer


class ActivityLogViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Company-scoped activity timeline (read + one-way review).

    Global gate: ``view_activitylog`` (list/retrieve), ``change_activitylog``
    (review). Rows are further narrowed by allowed sites and each entity's
    ``view_<model>`` permission.
    """

    serializer_class = ActivityLogSerializer
    queryset = ActivityLog.objects.none()
    http_method_names = ["get", "patch", "head", "options"]
    filterset_class = ActivityLogFilter
    pagination_class = ActivityLogPagination

    def get_queryset(self):
        return (
            activity_logs_for_user(self.request.user)
            .select_related("actor", "reviewed_by", "site", "labour")
            .order_by("-created_at", "-id")
        )

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
