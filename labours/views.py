from django.db import transaction
from django.utils.dateparse import parse_date
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.filters import SearchFilter
from rest_framework.response import Response
from rest_framework.settings import api_settings

from activity.hooks import (
    activity_after_create,
    activity_after_update,
    activity_before_destroy,
    snapshot_for,
)
from activity.models import ActivityEntityType
from activity.permissions import activity_logs_for_user
from activity.serializers import ActivityLogSerializer
from core import status_codes
from core.exceptions import (
    SubscriptionExpired,
    SubscriptionExpiredError,
    SubscriptionLimitExceeded,
    SubscriptionLimitExceededError,
)
from core.permissions import HasRecordSiteAccess, IsRecordNotSealed
from core.pagination import StandardPagination
from core.services import SubscriptionService
from sites.permissions import HasSitePermissions
from .filters import LabourFilter
from .permissions import (
    HasLabourCurrentSiteAccess,
    IsLabourActive,
    get_labour,
)
from .models import DailyRecord, Labour, LabourSession
from .serializers import (
    DailyRecordListSerializer,
    DailyRecordSerializer,
    LabourListSerializer,
    LabourSerializer,
    LabourSessionListSerializer,
    LabourSessionSerializer,
    RunningLabourSessionSerializer,
    SiteDailyRecordListSerializer,
    SiteDailyRecordSerializer,
)
from .services import (
    create_labour_session,
    delete_labour_session,
    get_running_session,
)


class LabourViewSet(viewsets.ModelViewSet):
    serializer_class = LabourSerializer
    queryset = Labour.objects.none()
    pagination_class = StandardPagination
    http_method_names = ["get", "post", "patch", "head", "options"]  # no PUT, no DELETE
    filter_backends = [*api_settings.DEFAULT_FILTER_BACKENDS, SearchFilter]
    filterset_class = LabourFilter
    search_fields = ["name"]

    def get_serializer_class(self):
        if self.action == "list":
            return LabourListSerializer
        return LabourSerializer

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Labour.objects.none()

        qs = Labour.objects.filter(company_id=user.company_id)
        if not user.is_companyadmin:
            qs = qs.filter(current_site__users__user_id=user.id)
        return qs.select_related("current_site").order_by("name")

    @transaction.atomic
    def perform_create(self, serializer):
        company = self.request.user.company
        try:
            SubscriptionService.validate_active_labour_limit(company)
        except SubscriptionLimitExceededError as exc:
            raise SubscriptionLimitExceeded(detail=str(exc))
        except SubscriptionExpiredError:
            raise SubscriptionExpired()
        serializer.save(
            company=company,
            is_active=True,
        )
        activity_after_create(self, serializer.instance)

    @transaction.atomic
    def perform_update(self, serializer):
        old = snapshot_for(serializer.instance)
        serializer.save()
        activity_after_update(self, serializer.instance, old)

    # Delete log still not included here. Because, currently we are not deleting labours.


class LabourDailyRecordViewSet(viewsets.ModelViewSet):
    """Nested under ``/labours/<labour_pk>/daily-records``."""

    serializer_class = DailyRecordSerializer
    queryset = DailyRecord.objects.none()
    pagination_class = StandardPagination
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filterset_fields = {
        "date": ["exact", "gte", "lte"],
        "billing": ["exact"],
        "is_sealed": ["exact"],
        "site": ["exact"],
    }

    def get_permissions(self):
        perms = list(api_settings.DEFAULT_PERMISSION_CLASSES)
        if self.action == "create":
            perms += [HasLabourCurrentSiteAccess, IsLabourActive]
        elif self.action in ("update", "partial_update", "destroy"):
            perms += [HasRecordSiteAccess, IsRecordNotSealed]
        else:
            perms += [HasLabourCurrentSiteAccess]
        return [permission() for permission in perms]

    def get_serializer_class(self):
        if self.action == "list":
            return DailyRecordListSerializer
        return DailyRecordSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["labour"] = get_labour(self.request, self)
        return context

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return DailyRecord.objects.none()

        return (
            DailyRecord.objects.filter(
                company_id=user.company_id,
                labour_id=self.kwargs["labour_pk"],
            )
            .select_related("labour", "site", "billing")
            .order_by("-date", "-id")
        )

    @transaction.atomic
    def perform_create(self, serializer):
        labour = get_labour(self.request, self)
        if labour.current_site_id is None:
            raise ValidationError(
                "Labour must be assigned to a site before creating records.",
                code=status_codes.LABOUR_UNASSIGNED,
            )
        serializer.save(
            labour=labour,
            site=labour.current_site,
            company=self.request.user.company,
            is_sealed=False,
        )
        activity_after_create(self, serializer.instance)

    @transaction.atomic
    def perform_update(self, serializer):
        old = snapshot_for(serializer.instance)
        serializer.save()
        activity_after_update(self, serializer.instance, old)

    @transaction.atomic
    def perform_destroy(self, instance):
        activity_before_destroy(self, instance)
        instance.delete()


class SiteDailyRecordViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Nested under ``/sites/<site_pk>/daily-records``.

    Only list and bulk create; the create payload is a list of records,
    each carrying its own ``labour``.
    """

    serializer_class = SiteDailyRecordSerializer
    queryset = DailyRecord.objects.none()
    pagination_class = StandardPagination
    permission_classes = [
        *api_settings.DEFAULT_PERMISSION_CLASSES,
        HasSitePermissions,
    ]
    filterset_fields = ["date", "billing", "is_sealed", "labour"]

    def get_serializer_class(self):
        if self.action == "list":
            return SiteDailyRecordListSerializer
        return SiteDailyRecordSerializer

    def get_serializer(self, *args, **kwargs):
        if self.action == "create":
            kwargs.setdefault("many", True)
        return super().get_serializer(*args, **kwargs)

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return DailyRecord.objects.none()

        return (
            DailyRecord.objects.filter(
                company_id=user.company_id,
                site_id=int(self.kwargs["site_pk"]),
            )
            .select_related("labour", "site", "billing")
            .order_by("-date", "-id")
        )

    def _parse_record_date(self, record_date):
        try:
            parsed = parse_date(record_date)
        except ValueError:
            parsed = None
        if parsed is None:
            raise ValidationError(
                {"date": "Enter a valid date (YYYY-MM-DD)."},
                code=status_codes.INVALID,
            )
        return parsed

    @action(
        detail=False,
        methods=["get"],
        url_path=r"(?P<record_date>\d{4}-\d{2}-\d{2})",
        url_name="by-date",
        pagination_class=None,
    )
    def by_date(self, request, site_pk=None, record_date=None, **kwargs):
        """Unpaginated list of all daily records for this site on ``record_date``."""
        parsed = self._parse_record_date(record_date)
        qs = self.get_queryset().filter(date=parsed)
        serializer = SiteDailyRecordListSerializer(qs, many=True)
        return Response(serializer.data)

    @action(
        detail=False,
        methods=["get"],
        url_path=r"(?P<record_date>\d{4}-\d{2}-\d{2})/pending_log",
        url_name="pending-log",
        pagination_class=None,
    )
    def pending_log(self, request, site_pk=None, record_date=None, **kwargs):
        """
        Unpaginated pending (unreviewed) daily-record activity for this date.
        It inherits the SiteDailyRecordViewSet's permission classes. 
        and check the `dailyrecord.view_dailyrecord` permission.
        """
        parsed = self._parse_record_date(record_date)
        qs = (
            activity_logs_for_user(request.user)
            .filter(
                site_id=int(site_pk),
                business_date=parsed,
                entity_type=ActivityEntityType.DAILY_RECORD,
                reviewed_at__isnull=True,
            )
            .select_related("actor", "reviewed_by", "site", "labour")
            .order_by("-created_at", "-id")
        )
        serializer = ActivityLogSerializer(qs, many=True)
        return Response(serializer.data)

    @transaction.atomic
    def perform_create(self, serializer):
        serializer.save(
            site_id=int(self.kwargs["site_pk"]),
            company=self.request.user.company,
            is_sealed=False,
        )
        activity_after_create(self, serializer.instance)



class LabourSessionViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Nested under ``/labours/<labour_pk>/sessions``.

    POST takes no payload: it closes the labour's open period (all
    DailyRecord rows after ``last_session_date``) into a new session and
    seals the affected records. DELETE only removes the most recent
    session, and only when current records still match its stored snapshot.
    """

    serializer_class = LabourSessionSerializer
    queryset = LabourSession.objects.none()
    pagination_class = StandardPagination
    http_method_names = ["get", "post", "delete", "head", "options"]
    filterset_fields = ["created_date", "start_date", "end_date"]

    def get_permissions(self):
        perms = list(api_settings.DEFAULT_PERMISSION_CLASSES)
        perms.append(HasLabourCurrentSiteAccess)
        if self.action == "create":
            perms.append(IsLabourActive)
        return [permission() for permission in perms]

    def get_serializer_class(self):
        if self.action == "list":
            return LabourSessionListSerializer
        return LabourSessionSerializer

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return LabourSession.objects.none()

        return (
            LabourSession.objects.filter(
                company_id=user.company_id,
                labour_id=self.kwargs["labour_pk"],
            )
            .select_related("labour")
            .order_by("-created_date", "-id")
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        labour = get_labour(request, self)
        running_session = get_running_session(labour)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            sessions = list(serializer.data)
            if running_session and self.paginator.page.number == 1:
                sessions.insert(0, self.get_serializer(running_session).data)
            return self.get_paginated_response(sessions)

        serializer = self.get_serializer(queryset, many=True)
        sessions = list(serializer.data)
        if running_session:
            sessions.insert(0, self.get_serializer(running_session).data)
        return Response(sessions)

    def create(self, request, *args, **kwargs):
        labour = get_labour(request, self)
        session = create_labour_session(labour=labour, user=request.user)
        serializer = LabourSessionSerializer(
            session, context=self.get_serializer_context()
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance):
        delete_labour_session(instance, actor=self.request.user)

    @action(detail=False, methods=["get"], url_path="running_session")
    def running_session(self, request, *args, **kwargs):
        labour = get_labour(request, self)
        running = get_running_session(labour)
        if running is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        serializer = RunningLabourSessionSerializer(running)
        return Response(serializer.data)
