from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.response import Response
from rest_framework.settings import api_settings

from activity.hooks import (
    activity_after_create,
    activity_after_update,
    snapshot_for,
)
from core.exceptions import (
    SubscriptionExpired,
    SubscriptionExpiredError,
    SubscriptionLimitExceeded,
    SubscriptionLimitExceededError,
)
from core.services import SubscriptionService
from .permissions import HasSiteAndLabourPermissions, get_labour
from .models import Labour, LabourSession
from .serializers import (
    LabourListSerializer,
    LabourSerializer,
    LabourSessionListSerializer,
    LabourSessionSerializer,
    RunningLabourSessionSerializer,
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
            .select_related("labour")
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
        delete_labour_session(instance, actor=self.request.user)

    @action(detail=False, methods=["get"], url_path="running_session")
    def running_session(self, request, *args, **kwargs):
        labour = get_labour(request, self)
        running = get_running_session(labour)
        if running is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        serializer = RunningLabourSessionSerializer(running)
        return Response(serializer.data)
