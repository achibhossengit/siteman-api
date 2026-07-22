import django_filters
from django.contrib.contenttypes.models import ContentType
from rest_framework import mixins, viewsets
from rest_framework.settings import api_settings

from sites.permissions import HasSitePermissions

from .models import ActivityLog
from .serializers import ActivityLogSerializer
from .services import filter_logs_by_viewable_resources


class ActivityLogFilter(django_filters.FilterSet):
    """Filter by CT id, or ``app_label.model`` via ``model`` query param."""

    model = django_filters.CharFilter(method="filter_model")
    created_at = django_filters.DateFromToRangeFilter()

    class Meta:
        model = ActivityLog
        fields = ["content_type", "object_id", "action_flag", "actor", "created_at"]

    def filter_model(self, queryset, name, value):
        # Expect "labours.labourpayment"
        if not value or "." not in value:
            return queryset.none()
        app_label, model = value.split(".", 1)
        try:
            ct = ContentType.objects.get(app_label=app_label, model=model)
        except ContentType.DoesNotExist:
            return queryset.none()
        return queryset.filter(content_type=ct)


class ActivityLogViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Nested under ``/sites/<site_pk>/activity-logs``.

    Same stack as other site children (model perms + site membership).
    Rows are further limited to content types the user can ``view_*``.
    """

    serializer_class = ActivityLogSerializer
    queryset = ActivityLog.objects.none()
    permission_classes = [
        *api_settings.DEFAULT_PERMISSION_CLASSES,
        HasSitePermissions,
    ]
    http_method_names = ["get", "head", "options"]
    filterset_class = ActivityLogFilter

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated or not user.company_id:
            return ActivityLog.objects.none()

        qs = ActivityLog.objects.filter(
            company_id=user.company_id,
            site_id=int(self.kwargs["site_pk"]),
        ).select_related("actor", "content_type", "company", "site")
        return filter_logs_by_viewable_resources(qs, user).order_by(
            "-created_at", "-id"
        )
