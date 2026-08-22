from django.contrib import admin
from django.contrib.admin.options import IncorrectLookupParameters
from django.core.exceptions import ValidationError
from django.db import models

from sites.models import Site


COMPANY_LOOKUP = "company__id__exact"


def selected_company_id(request):
    return request.GET.get(COMPANY_LOOKUP) or request.GET.get("company")


class CompanyListFilter(admin.RelatedFieldListFilter):
    """Keep the company filter visible even when there is only one company."""

    def has_output(self):
        return True


class SiteListFilter(admin.SimpleListFilter):
    """Shown only after a company is selected; lists that company's sites."""

    title = "site"
    parameter_name = "site"
    site_field = "site"

    def lookups(self, request, model_admin):
        company_id = selected_company_id(request)
        if not company_id:
            return ()
        return tuple(
            Site.objects.filter(company_id=company_id)
            .order_by("name")
            .values_list("id", "name")
        )

    def queryset(self, request, queryset):
        if not self.value():
            return queryset
        company_id = selected_company_id(request)
        sites = Site.objects.filter(pk=self.value())
        if company_id:
            sites = sites.filter(company_id=company_id)
        if not sites.exists():
            return queryset
        return queryset.filter(**{f"{self.site_field}_id": self.value()})


class CurrentSiteListFilter(SiteListFilter):
    parameter_name = "current_site"
    site_field = "current_site"


class DateRangeFilter(admin.FieldListFilter):
    """From/to date inputs so any date range can be selected."""

    template = "admin/date_range_filter.html"

    def __init__(self, field, request, params, model, model_admin, field_path):
        if isinstance(field, models.DateTimeField):
            self.lookup_kwarg_gte = f"{field_path}__date__gte"
            self.lookup_kwarg_lte = f"{field_path}__date__lte"
        else:
            self.lookup_kwarg_gte = f"{field_path}__gte"
            self.lookup_kwarg_lte = f"{field_path}__lte"
        super().__init__(field, request, params, model, model_admin, field_path)
        for key in list(self.used_parameters):
            if not self._flat(key):
                self.used_parameters.pop(key, None)
        self.value_gte = self._flat(self.lookup_kwarg_gte)
        self.value_lte = self._flat(self.lookup_kwarg_lte)

    def _flat(self, key):
        value = self.used_parameters.get(key, "")
        if isinstance(value, (list, tuple)):
            value = value[-1] if value else ""
        return str(value) if value else ""

    def expected_parameters(self):
        return [self.lookup_kwarg_gte, self.lookup_kwarg_lte]

    def queryset(self, request, queryset):
        filters = {}
        for key in self.expected_parameters():
            value = self._flat(key)
            if value:
                filters[key] = value
        if not filters:
            return queryset
        try:
            return queryset.filter(**filters)
        except (ValueError, ValidationError) as exc:
            raise IncorrectLookupParameters(exc) from exc

    def get_facet_counts(self, pk_attname, filtered_qs):
        return {}

    def choices(self, changelist):
        hidden = [
            (key, value)
            for key, value in changelist.params.items()
            if key not in self.expected_parameters()
        ]
        yield {
            "hidden": hidden,
            "clear_query": changelist.get_query_string(
                remove=self.expected_parameters()
            ),
        }


class ReadOnlyModelAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
