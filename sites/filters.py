import django_filters

from .models import PrivateSiteCash, SiteCash


class SiteCashFilter(django_filters.FilterSet):
    date = django_filters.DateFilter(field_name="date")
    date__gte = django_filters.DateFilter(field_name="date", lookup_expr="gte")
    date__lte = django_filters.DateFilter(field_name="date", lookup_expr="lte")

    class Meta:
        model = SiteCash
        fields = ["type", "date", "billing"]


class PrivateSiteCashFilter(django_filters.FilterSet):
    date = django_filters.DateFilter(field_name="date")
    date__gte = django_filters.DateFilter(field_name="date", lookup_expr="gte")
    date__lte = django_filters.DateFilter(field_name="date", lookup_expr="lte")

    class Meta:
        model = PrivateSiteCash
        fields = ["type", "date", "billing"]
