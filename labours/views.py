from django.db import transaction
from django.db.utils import IntegrityError
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ErrorDetail, ValidationError
from rest_framework.filters import SearchFilter
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.exceptions import NotFound
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
    LabourSessionListSerializer,
    LabourSessionSerializer,
    RunningLabourSessionSerializer,
    SiteLabourAttendanceListSerializer,
    SiteLabourAttendanceSerializer,
    SiteLabourPaymentListSerializer,
    SiteLabourPaymentSerializer,
)
from .services import (
    create_labour_session,
    delete_labour_session,
    get_running_session,
)


class LabourViewSet(viewsets.ModelViewSet):
    serializer_class = LabourSerializer
    queryset = Labour.objects.none()
    http_method_names = ["get", "post", "patch", "head", "options"]  # no PUT, no DELETE
    filter_backends = [*api_settings.DEFAULT_FILTER_BACKENDS, SearchFilter]
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

        qs = Labour.objects.filter(company_id=user.company_id)
        if not user.is_companyadmin:
            qs = qs.filter(current_site__users__user_id=user.id)
        return qs.select_related("current_site", "created_by").order_by("name")

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
    filterset_fields = {
        "type": ["exact"],
        "category": ["exact"],
        "date": ["exact", "gte", "lte"],
        "is_sealed": ["exact"],
        "site": ["exact"],
    }

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
        if labour.current_site_id is None:
            raise ValidationError(
                "Labour must be assigned to a site before creating records.",
                code=status_codes.LABOUR_UNASSIGNED,
            )
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
    filterset_fields = {
        "date": ["exact", "gte", "lte"],
        "billing": ["exact"],
        "is_sealed": ["exact"],
        "site": ["exact"],
    }

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
        if labour.current_site_id is None:
            raise ValidationError(
                "Labour must be assigned to a site before creating records.",
                code=status_codes.LABOUR_UNASSIGNED,
            )
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
    filterset_fields = ["created_date", "start_date", "end_date"]

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
            .select_related("labour", "created_by")
            .order_by("-created_date", "-id")
        )
        
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        sessions = serializer.data
        labour = get_labour(request, self)
        running_session = get_running_session(labour)
        if running_session:
            serialized_running_session = self.get_serializer(running_session)
            sessions.insert(0, serialized_running_session.data)
        return Response(sessions)

    def create(self, request, *args, **kwargs):
        labour = get_labour(request, self)
        session = create_labour_session(labour=labour, user=request.user)
        serializer = LabourSessionSerializer(
            session, context=self.get_serializer_context()
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance):
        delete_labour_session(instance)

    @action(detail=False, methods=["get"], url_path="running_session")
    def running_session(self, request, *args, **kwargs):
        labour = get_labour(request, self)
        session = get_running_session(labour)
        if session is None:
            raise NotFound("No running (open) session found for this labour.")
        serializer = RunningLabourSessionSerializer(session)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="latest_session")
    def latest_session(self, request, *args, **kwargs):
        labour = get_labour(request, self)
        running_session = get_running_session(labour)
        if running_session:
            serializer = RunningLabourSessionSerializer(running_session)
            return Response(serializer.data)
        session = LabourSession.objects.filter(labour=labour).order_by("-created_date", "-id").first()
        if session is None:
            raise NotFound("No Session Found!")
        serializer = LabourSessionSerializer(session)
        return Response(serializer.data)
    

# ==== Site Labour Related Views ====

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
                site_id=int(self.kwargs["site_pk"]),
            )
            .select_related("labour", "site", "created_by")
            .order_by("-date", "-id")
        )

    @transaction.atomic
    def perform_create(self, serializer):
        try:
            serializer.save(
                site_id=int(self.kwargs["site_pk"]),
                company=self.request.user.company,
                created_by=self.request.user,
                is_sealed=False,
            )
        except IntegrityError:
            raise ValidationError(
                "A payment of this type already exists for a labour on this date.",
                code=status_codes.RECORD_UNIQUE_CONSTRAINT_VIOLATION,
            )

    @action(detail=False, methods=["patch"], url_path="bulk-update")
    @transaction.atomic
    def bulk_update(self, request, *args, **kwargs):
        """All-or-nothing partial update; each item carries its own ``id``."""

        if not isinstance(request.data, list):
            raise ValidationError("Expected a list of payments.")
        if not request.data:
            raise ValidationError("At least one payment is required.")

        # Error dict keys are stringified indexes; the error formatter drops
        # falsy attrs, so int 0 would lose its item index in ``attr``.
        errors = {}
        ids = []
        for index, item in enumerate(request.data):
            if not isinstance(item, dict):
                errors[str(index)] = {"non_field_errors": ["Expected an object."]}
            elif not isinstance(item.get("id"), int) or isinstance(
                item.get("id"), bool
            ):
                errors[str(index)] = {"id": ["A valid integer id is required."]}
            else:
                ids.append(item["id"])
        if errors:
            raise ValidationError(errors)

        if len(ids) != len(set(ids)):
            raise ValidationError("Duplicate ids are not allowed.")

        # ``of=("self",)`` locks only payment rows; plain select_for_update
        # fails on the nullable side of the select_related joins.
        records = {
            record.pk: record
            for record in self.get_queryset()
            .select_for_update(of=("self",))
            .filter(pk__in=ids)
        }

        item_serializers = []
        for index, item in enumerate(request.data):
            record = records.get(item["id"])
            if record is None:
                errors[str(index)] = {"id": ["Payment not found."]}
                continue
            if record.is_sealed:
                errors[str(index)] = {
                    "id": [
                        ErrorDetail(
                            "Sealed records cannot be updated.",
                            code=status_codes.RECORD_SEALED,
                        )
                    ]
                }
                continue

            data = {key: value for key, value in item.items() if key != "id"}
            if not data:
                errors[str(index)] = {
                    "non_field_errors": ["At least one field must be provided."]
                }
                continue

            serializer = self.get_serializer(record, data=data, partial=True)
            if not serializer.is_valid():
                errors[str(index)] = serializer.errors
                continue
            item_serializers.append(serializer)

        if errors:
            raise ValidationError(errors)

        try:
            updated = [serializer.save() for serializer in item_serializers]
        except IntegrityError:
            raise ValidationError(
                "A payment of this type already exists for a labour on this date.",
                code=status_codes.RECORD_UNIQUE_CONSTRAINT_VIOLATION,
            )

        output = self.get_serializer(updated, many=True)
        return Response(output.data)


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
                site_id=int(self.kwargs["site_pk"]),
            )
            .select_related("labour", "site", "billing", "created_by")
            .order_by("-date", "-id")
        )

    @transaction.atomic
    def perform_create(self, serializer):
        try:
            serializer.save(
                site_id=int(self.kwargs["site_pk"]),
                company=self.request.user.company,
                created_by=self.request.user,
                is_sealed=False,
            )
        except IntegrityError:
            raise ValidationError(
                "Attendance already exists for a labour on this date.",
                code=status_codes.RECORD_UNIQUE_CONSTRAINT_VIOLATION,
            )

    @action(detail=False, methods=["patch"], url_path="bulk-update")
    @transaction.atomic
    def bulk_update(self, request, *args, **kwargs):
        """All-or-nothing partial update; each item carries its own ``id``."""

        if not isinstance(request.data, list):
            raise ValidationError("Expected a list of attendances.")
        if not request.data:
            raise ValidationError("At least one attendance is required.")

        # Error dict keys are stringified indexes; the error formatter drops
        # falsy attrs, so int 0 would lose its item index in ``attr``.
        errors = {}
        ids = []
        for index, item in enumerate(request.data):
            if not isinstance(item, dict):
                errors[str(index)] = {"non_field_errors": ["Expected an object."]}
            elif not isinstance(item.get("id"), int) or isinstance(
                item.get("id"), bool
            ):
                errors[str(index)] = {"id": ["A valid integer id is required."]}
            else:
                ids.append(item["id"])
        if errors:
            raise ValidationError(errors)

        if len(ids) != len(set(ids)):
            raise ValidationError("Duplicate ids are not allowed.")

        # ``of=("self",)`` locks only attendance rows; plain select_for_update
        # fails on the nullable side of the select_related joins.
        records = {
            record.pk: record
            for record in self.get_queryset()
            .select_for_update(of=("self",))
            .filter(pk__in=ids)
        }

        item_serializers = []
        for index, item in enumerate(request.data):
            record = records.get(item["id"])
            if record is None:
                errors[str(index)] = {"id": ["Attendance not found."]}
                continue
            if record.is_sealed:
                errors[str(index)] = {
                    "id": [
                        ErrorDetail(
                            "Sealed records cannot be updated.",
                            code=status_codes.RECORD_SEALED,
                        )
                    ]
                }
                continue

            data = {key: value for key, value in item.items() if key != "id"}
            if not data:
                errors[str(index)] = {
                    "non_field_errors": ["At least one field must be provided."]
                }
                continue

            serializer = self.get_serializer(record, data=data, partial=True)
            if not serializer.is_valid():
                errors[str(index)] = serializer.errors
                continue
            item_serializers.append(serializer)

        if errors:
            raise ValidationError(errors)

        try:
            updated = [serializer.save() for serializer in item_serializers]
        except IntegrityError:
            raise ValidationError(
                "Attendance already exists for a labour on this date.",
                code=status_codes.RECORD_UNIQUE_CONSTRAINT_VIOLATION,
            )

        output = self.get_serializer(updated, many=True)
        return Response(output.data)
