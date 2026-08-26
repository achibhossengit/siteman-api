from django.db import transaction
from django.db.models import ProtectedError, RestrictedError
from django.db.utils import IntegrityError
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.settings import api_settings

from activity.hooks import (
    activity_after_create,
    activity_after_update,
    activity_before_destroy,
    snapshot_for,
)
from activity.models import ActivityEntityType
from activity.services import pending_activities_by_entity
from core import status_codes
from core.pagination import StandardPagination
from core.permissions import ActiveSubscriptionOrReadOnly
from core.services import SubscriptionService
from core.exceptions import (
    SubscriptionLimitExceededError,
    SubscriptionExpiredError,
    SubscriptionExpired,
    SubscriptionLimitExceeded,
)
from .filters import PrivateSiteCashFilter, SiteCashFilter
from .models import BillingCategory, PrivateSiteCash, Site, SiteCash
from .permissions import HasSitePermissions
from .serializers import (
    BillingCategoryListSerializer,
    BillingCategorySerializer,
    PrivateSiteCashListSerializer,
    PrivateSiteCashSerializer,
    SiteCashListSerializer,
    SiteCashSerializer,
    SiteDailyReportSerializer,
    SiteListSerializer,
    SiteSerializer,
)
from .services import build_site_daily_report


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
    pagination_class = StandardPagination
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]  # no PUT
    filter_backends = [*api_settings.DEFAULT_FILTER_BACKENDS, SearchFilter]
    filterset_fields = ["is_active", "is_closed"]
    search_fields = ["name"]

    def get_serializer_class(self):
        if self.action == "list":
            return SiteListSerializer
        return SiteSerializer

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Site.objects.none()

        qs = Site.objects.filter(company_id=user.company_id)
        if not user.is_companyadmin:
            qs = qs.filter(users__user_id=user.id)
        return qs.order_by("-created_at")

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
            closed_at=None,
            is_active=True,
        )
        activity_after_create(self, serializer.instance)

    @transaction.atomic
    def perform_update(self, serializer):
        old = snapshot_for(serializer.instance)
        serializer.save()
        activity_after_update(self, serializer.instance, old)

    def perform_destroy(self, instance):
        # children FKs use on_delete=RESTRICT/PROTECT — the DB layer is the
        # single source of truth for "site still has records"
        try:
            with transaction.atomic():
                activity_before_destroy(self, instance)
                instance.delete()
        except (ProtectedError, RestrictedError):
            raise serializers.ValidationError(
                detail="This site has existing records; delete them or close the site first.",
                code=status_codes.SITE_HAS_RECORDS,
            )

    @action(
        detail=True,
        methods=["get"],
        url_path="daily-reports",
        permission_classes=[IsAuthenticated, ActiveSubscriptionOrReadOnly, HasSitePermissions],
    )
    def daily_reports(self, request, pk=None, **kwargs):
        """Day summary for this site. Query param ``date`` (YYYY-MM-DD) is optional; defaults to today.
        """
        date_raw = request.query_params.get("date")
        if date_raw:
            report_date = parse_date(date_raw)
            if report_date is None:
                raise serializers.ValidationError(
                    {"date": "Enter a valid date (YYYY-MM-DD)."},
                    code=status_codes.INVALID,
                )
        else:
            report_date = timezone.localdate()

        site = self.get_object()
        include_private = request.user.has_perm("sites.view_privatesitecash")
        report = build_site_daily_report(
            site, report_date, include_private=include_private
        )
        serializer = SiteDailyReportSerializer(data=report)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)


class SiteBillingCategoryViewSet(viewsets.ModelViewSet):
    """Nested under ``/sites/<site_pk>/billing-categories``."""

    serializer_class = BillingCategorySerializer
    queryset = BillingCategory.objects.none()
    pagination_class = StandardPagination
    permission_classes = [
        *api_settings.DEFAULT_PERMISSION_CLASSES,
        HasSitePermissions,
    ]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filterset_fields = ["is_active", "is_done"]

    def get_serializer_class(self):
        if self.action == "list":
            return BillingCategoryListSerializer
        return BillingCategorySerializer

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return BillingCategory.objects.none()

        return (
            BillingCategory.objects.filter(
                company_id=user.company_id,
                site_id=int(self.kwargs["site_pk"]),
            )
            .select_related("site")
            .order_by("display_order", "id")
        )

    def _apply_status_defaults(self, serializer):
        data = serializer.validated_data
        # Mark as done => deactivate.
        if data.get("is_done") is True:
            data["is_active"] = False
        elif serializer.instance is None and "is_active" not in serializer.initial_data:
            # HTML form omission coerces missing booleans to False; restore model default.
            data["is_active"] = True

    def perform_create(self, serializer):
        self._apply_status_defaults(serializer)
        try:
            with transaction.atomic():
                serializer.save(
                    site_id=int(self.kwargs["site_pk"]),
                    company=self.request.user.company,
                )
                activity_after_create(self, serializer.instance)
        except IntegrityError:
            raise serializers.ValidationError(
                "A billing category with this name already exists on this site.",
                code=status_codes.BILLING_CATEGORY_NAME_EXISTS,
            )

    def perform_update(self, serializer):
        self._apply_status_defaults(serializer)
        old = snapshot_for(serializer.instance)
        try:
            with transaction.atomic():
                serializer.save()
                activity_after_update(self, serializer.instance, old)
        except IntegrityError:
            raise serializers.ValidationError(
                "A billing category with this name already exists on this site.",
                code=status_codes.BILLING_CATEGORY_NAME_EXISTS,
            )

    @transaction.atomic
    def perform_destroy(self, instance):
        activity_before_destroy(self, instance)
        instance.delete()


class SiteCashViewSet(viewsets.ModelViewSet):
    """Nested under ``/sites/<site_pk>/cash``."""

    serializer_class = SiteCashSerializer
    queryset = SiteCash.objects.none()
    pagination_class = StandardPagination
    permission_classes = [
        *api_settings.DEFAULT_PERMISSION_CLASSES,
        HasSitePermissions,
    ]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filterset_class = SiteCashFilter

    def get_serializer_class(self):
        if self.action == "list":
            return SiteCashListSerializer
        return SiteCashSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["pending_activities_map"] = getattr(
            self, "_pending_activities_map", {}
        )
        return context

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        objects = page if page is not None else list(queryset)
        self._pending_activities_map = pending_activities_by_entity(
            company_id=request.user.company_id,
            entity_type=ActivityEntityType.SITE_CASH,
            entity_ids=[obj.pk for obj in objects],
        )
        serializer = self.get_serializer(objects, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return SiteCash.objects.none()

        return (
            SiteCash.objects.filter(
                company_id=user.company_id,
                site_id=int(self.kwargs["site_pk"]),
            )
            .order_by("-date", "-id")
        )

    @transaction.atomic
    def perform_create(self, serializer):
        serializer.save(
            site_id=int(self.kwargs["site_pk"]),
            company=self.request.user.company,
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


class PrivateSiteCashViewSet(viewsets.ModelViewSet):
    """Nested under ``/sites/<site_pk>/private-cash``."""

    serializer_class = PrivateSiteCashSerializer
    queryset = PrivateSiteCash.objects.none()
    pagination_class = StandardPagination
    permission_classes = [
        *api_settings.DEFAULT_PERMISSION_CLASSES,
        HasSitePermissions,
    ]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filterset_class = PrivateSiteCashFilter

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
                site_id=int(self.kwargs["site_pk"]),
            )
            .select_related("site", "billing")
            .order_by("-date", "-id")
        )

    @transaction.atomic
    def perform_create(self, serializer):
        serializer.save(
            site_id=int(self.kwargs["site_pk"]),
            company=self.request.user.company,
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
