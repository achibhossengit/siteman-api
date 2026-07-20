from django.db import transaction
from django.db.utils import IntegrityError
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.filters import SearchFilter
from rest_framework.response import Response
from rest_framework.settings import api_settings

from core import status_codes
from core.exceptions import (
    SubscriptionExpired,
    SubscriptionExpiredError,
    SubscriptionLimitExceeded,
    SubscriptionLimitExceededError,
)
from core.services import SubscriptionService
from core.permissions import RecordUpdateDeletePermissions
from sites.permissions import HasSitePermissions
from .permissions import HasSiteAndLabourPermissions, get_labour
from .models import Attendance, Labour, LabourPayment, LabourSession
from .serializers import (
    AttendanceListSerializer,
    AttendanceSerializer,
    LabourListSerializer,
    LabourPaymentListSerializer,
    LabourPaymentSerializer,
    LabourSerializer,
    LabourSessionSerializer,
    SiteLabourAttendanceListSerializer,
    SiteLabourAttendanceSerializer,
    SiteLabourPaymentListSerializer,
    SiteLabourPaymentSerializer,
)
from .services import create_labour_session, delete_labour_session


class LabourViewSet(viewsets.ModelViewSet):
    serializer_class = LabourSerializer
    queryset = Labour.objects.none()
    http_method_names = ["get", "post", "patch", "head", "options"]  # no PUT, no DELETE
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["is_active", "current_site"]
    search_fields = ["name"]

    def get_serializer_class(self):
        if self.action == "list":
            return LabourListSerializer
        return LabourSerializer

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Labour.objects.none()

        return (
            Labour.objects.filter(company_id=user.company_id)
            .select_related("current_site", "created_by")
            .order_by("name")
        )

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
            created_by=self.request.user,
            is_active=True,
        )


class LabourPaymentViewSet(viewsets.ModelViewSet):
    """Nested under ``/labours/<labour_pk>/payments``."""

    serializer_class = LabourPaymentSerializer
    queryset = LabourPayment.objects.none()
    permission_classes = [
        *api_settings.DEFAULT_PERMISSION_CLASSES,
        HasSiteAndLabourPermissions,
        RecordUpdateDeletePermissions,
    ]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["type", "category", "date", "is_sealed", "site"]

    def get_serializer_class(self):
        if self.action == "list":
            return LabourPaymentListSerializer
        return LabourPaymentSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["labour"] = get_labour(self.request, self)
        return context

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return LabourPayment.objects.none()

        return (
            LabourPayment.objects.filter(
                company_id=user.company_id,
                labour_id=self.kwargs["labour_pk"],
            )
            .select_related("labour", "site", "created_by")
            .order_by("-date", "-id")
        )

    def perform_create(self, serializer):
        labour = get_labour(self.request, self)
        try:
            serializer.save(
                labour=labour,
                site=labour.current_site,
                company=self.request.user.company,
                created_by=self.request.user,
                is_sealed=False,
            )
        except IntegrityError:
            raise ValidationError(
                "A payment of this type already exists for this labour on this date.",
                code=status_codes.RECORD_UNIQUE_CONSTRAINT_VIOLATION,
            )

    def perform_update(self, serializer):
        try:
            serializer.save()
        except IntegrityError:
            raise ValidationError(
                "A payment of this type already exists for this labour on this date.",
                code=status_codes.RECORD_UNIQUE_CONSTRAINT_VIOLATION,
            )


class SiteLabourPaymentViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Nested under ``/sites/<site_pk>/labour-payments``.

    Only list and bulk create; the create payload is a list of payments,
    each carrying its own ``labour``.
    """

    serializer_class = SiteLabourPaymentSerializer
    queryset = LabourPayment.objects.none()
    permission_classes = [
        *api_settings.DEFAULT_PERMISSION_CLASSES,
        HasSitePermissions,
    ]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["type", "category", "date", "is_sealed", "labour"]

    def get_serializer_class(self):
        if self.action == "list":
            return SiteLabourPaymentListSerializer
        return SiteLabourPaymentSerializer

    def get_serializer(self, *args, **kwargs):
        if self.action == "create":
            kwargs.setdefault("many", True)
        return super().get_serializer(*args, **kwargs)

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return LabourPayment.objects.none()

        return (
            LabourPayment.objects.filter(
                company_id=user.company_id,
                site_id=self.kwargs["site_pk"],
            )
            .select_related("labour", "site", "created_by")
            .order_by("-date", "-id")
        )

    @transaction.atomic
    def perform_create(self, serializer):
        try:
            serializer.save(
                site_id=self.kwargs["site_pk"],
                company=self.request.user.company,
                created_by=self.request.user,
                is_sealed=False,
            )
        except IntegrityError:
            raise ValidationError(
                "A payment of this type already exists for a labour on this date.",
                code=status_codes.RECORD_UNIQUE_CONSTRAINT_VIOLATION,
            )


class SiteLabourAttendanceViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Nested under ``/sites/<site_pk>/labour-attendances``.

    Only list and bulk create; the create payload is a list of
    attendances, each carrying its own ``labour``.
    """

    serializer_class = SiteLabourAttendanceSerializer
    queryset = Attendance.objects.none()
    permission_classes = [
        *api_settings.DEFAULT_PERMISSION_CLASSES,
        HasSitePermissions,
    ]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["date", "billing", "is_sealed", "labour"]

    def get_serializer_class(self):
        if self.action == "list":
            return SiteLabourAttendanceListSerializer
        return SiteLabourAttendanceSerializer

    def get_serializer(self, *args, **kwargs):
        if self.action == "create":
            kwargs.setdefault("many", True)
        return super().get_serializer(*args, **kwargs)

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Attendance.objects.none()

        return (
            Attendance.objects.filter(
                company_id=user.company_id,
                site_id=self.kwargs["site_pk"],
            )
            .select_related("labour", "site", "billing", "created_by")
            .order_by("-date", "-id")
        )

    @transaction.atomic
    def perform_create(self, serializer):
        try:
            serializer.save(
                site_id=self.kwargs["site_pk"],
                company=self.request.user.company,
                created_by=self.request.user,
                is_sealed=False,
            )
        except IntegrityError:
            raise ValidationError(
                "Attendance already exists for a labour on this date.",
                code=status_codes.RECORD_UNIQUE_CONSTRAINT_VIOLATION,
            )


class LabourAttendanceViewSet(viewsets.ModelViewSet):
    """Nested under ``/labours/<labour_pk>/attendances``."""

    serializer_class = AttendanceSerializer
    queryset = Attendance.objects.none()
    permission_classes = [
        *api_settings.DEFAULT_PERMISSION_CLASSES,
        HasSiteAndLabourPermissions,
        RecordUpdateDeletePermissions,
    ]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["date", "billing", "is_sealed", "site"]

    def get_serializer_class(self):
        if self.action == "list":
            return AttendanceListSerializer
        return AttendanceSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["labour"] = get_labour(self.request, self)
        return context

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Attendance.objects.none()

        return (
            Attendance.objects.filter(
                company_id=user.company_id,
                labour_id=self.kwargs["labour_pk"],
            )
            .select_related("labour", "site", "billing", "created_by")
            .order_by("-date", "-id")
        )

    def perform_create(self, serializer):
        labour = get_labour(self.request, self)
        try:
            serializer.save(
                labour=labour,
                site=labour.current_site,
                company=self.request.user.company,
                created_by=self.request.user,
                is_sealed=False,
            )
        except IntegrityError:
            raise ValidationError(
                "Attendance already exists for this labour on this date.",
                code=status_codes.RECORD_UNIQUE_CONSTRAINT_VIOLATION,
            )

    def perform_update(self, serializer):
        try:
            serializer.save()
        except IntegrityError:
            raise ValidationError(
                "Attendance already exists for this labour on this date.",
                code=status_codes.RECORD_UNIQUE_CONSTRAINT_VIOLATION,
            )


class LabourSessionViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Nested under ``/labours/<labour_pk>/sessions``.

    POST takes no payload: it closes the labour's open period (all
    records after ``last_session_date``) into a new session and seals
    the affected records. DELETE only removes the most recent session,
    and only when current records still match its stored snapshot.
    """

    serializer_class = LabourSessionSerializer
    queryset = LabourSession.objects.none()
    permission_classes = [
        *api_settings.DEFAULT_PERMISSION_CLASSES,
        HasSiteAndLabourPermissions,
    ]
    http_method_names = ["get", "post", "delete", "head", "options"]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["created_date", "start_date", "end_date"]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return LabourSession.objects.none()

        return (
            LabourSession.objects.filter(
                company_id=user.company_id,
                labour_id=self.kwargs["labour_pk"],
            )
            .select_related("labour", "created_by")
            .order_by("-created_date", "-id")
        )

    def create(self, request, *args, **kwargs):
        labour = get_labour(request, self)
        session = create_labour_session(labour=labour, user=request.user)
        serializer = LabourSessionSerializer(
            session, context=self.get_serializer_context()
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance):
        delete_labour_session(instance)
