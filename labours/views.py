from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.filters import SearchFilter

from core.exceptions import (
    SubscriptionExpired,
    SubscriptionExpiredError,
    SubscriptionLimitExceeded,
    SubscriptionLimitExceededError,
)
from core.services import SubscriptionService
from .models import Labour
from .serializers import LabourListSerializer, LabourSerializer


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
