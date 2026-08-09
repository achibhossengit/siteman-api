import django_filters
from django_filters.constants import EMPTY_VALUES
from rest_framework.exceptions import ValidationError

from core import status_codes
from .models import Labour

_NULL_VALUES = frozenset({"null", "none"})


class LabourFilter(django_filters.FilterSet):
    current_site = django_filters.CharFilter(method="filter_current_site")

    class Meta:
        model = Labour
        fields = ["is_active", "current_site"]

    def filter_current_site(self, queryset, name, value):
        if value in EMPTY_VALUES:
            return queryset
        if str(value).strip().lower() in _NULL_VALUES:
            return queryset.filter(current_site__isnull=True)
        try:
            site_id = int(value)
        except (TypeError, ValueError):
            raise ValidationError(
                {"current_site": "Enter a valid site id or null."},
                code=status_codes.INVALID,
            )
        return queryset.filter(current_site_id=site_id)
