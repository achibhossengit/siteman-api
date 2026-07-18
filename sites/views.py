from django.db import transaction
from django.db.models import ProtectedError, RestrictedError
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, viewsets
from rest_framework.settings import api_settings

from core import status_codes
from core.services import SubscriptionService
from core.exceptions import SubscriptionLimitExceededError, SubscriptionExpiredError, SubscriptionExpired, SubscriptionLimitExceeded
from .models import PrivateSiteCash, Site, SiteCash
from .permissions import HasSitePermissions
from .serializers import (
    PrivateSiteCashListSerializer,
    PrivateSiteCashSerializer,
    SiteCashListSerializer,
    SiteCashSerializer,
    SiteListSerializer,
    SiteSerializer,
)


class SiteViewSet(viewsets.ModelViewSet):
    """
    Permission totally goes to the django default permissions system.
    - Sitemanager, SiteAuditor: provide view permission
    - CompanyAdmin: provide all permissions
    
    Here, subscription limit check is need for creating new site.
    `is_closed` is readonly in SiteSerializers, so reopening not possible.
    site `close` and `reopen` will handled by differnet views.
    """
    serializer_class = SiteSerializer
    queryset = Site.objects.none()  # real queryset in get_queryset; here for router/schema
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]  # no PUT
    filterset_fields = ["is_active", "is_closed"]

    def get_serializer_class(self):
        if self.action == "list":
            return SiteListSerializer
        return SiteSerializer

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Site.objects.none()

        return (
            Site.objects.filter(company_id=user.company_id)
            .select_related("created_by")
            .order_by("-created_at")
        )

    @transaction.atomic
    def perform_create(self, serializer):
        company = self.request.user.company
        # validate active subscription and open site limit
        try:
            SubscriptionService.validate_open_site_limit(company)
        except SubscriptionLimitExceededError:
            raise SubscriptionLimitExceeded()
        except SubscriptionExpiredError:
            raise SubscriptionExpired()
        serializer.save(
            company=company,
            created_by=self.request.user,
            closed_at=None,
            is_active=True,
        )        

    def perform_destroy(self, instance):
        # children FKs use on_delete=RESTRICT/PROTECT — the DB layer is the
        # single source of truth for "site still has records"
        try:
            instance.delete()
        except (ProtectedError, RestrictedError):
            raise serializers.ValidationError(
                detail="This site has existing records; delete them or close the site first.",
                code=status_codes.SITE_HAS_RECORDS,
            )


class SiteCashViewSet(viewsets.ModelViewSet):
    """Nested under ``/sites/<site_pk>/cash``."""

    serializer_class = SiteCashSerializer
    queryset = SiteCash.objects.none()
    permission_classes = [
        *api_settings.DEFAULT_PERMISSION_CLASSES,
        HasSitePermissions,
    ]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filterset_fields = ["type", "category", "date", "billing"]

    def get_serializer_class(self):
        if self.action == "list":
            return SiteCashListSerializer
        return SiteCashSerializer

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return SiteCash.objects.none()

        return (
            SiteCash.objects.filter(
                company_id=user.company_id,
                site_id=self.kwargs["site_pk"],
            )
            .select_related("site", "billing", "created_by")
            .order_by("-date", "-id")
        )

    def perform_create(self, serializer):
        serializer.save(
            site_id=self.kwargs["site_pk"],
            company=self.request.user.company,
            created_by=self.request.user,
        )


class PrivateSiteCashViewSet(viewsets.ModelViewSet):
    """Nested under ``/sites/<site_pk>/private-cash``."""

    serializer_class = PrivateSiteCashSerializer
    queryset = PrivateSiteCash.objects.none()
    permission_classes = [
        *api_settings.DEFAULT_PERMISSION_CLASSES,
        HasSitePermissions,
    ]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filterset_fields = ["type", "date", "billing"]

    def get_serializer_class(self):
        if self.action == "list":
            return PrivateSiteCashListSerializer
        return PrivateSiteCashSerializer

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return PrivateSiteCash.objects.none()

        return (
            PrivateSiteCash.objects.filter(
                company_id=user.company_id,
                site_id=self.kwargs["site_pk"],
            )
            .select_related("site", "billing", "created_by")
            .order_by("-date", "-id")
        )

    def perform_create(self, serializer):
        serializer.save(
            site_id=self.kwargs["site_pk"],
            company=self.request.user.company,
            created_by=self.request.user,
        )
