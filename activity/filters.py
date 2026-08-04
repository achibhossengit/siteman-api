import django_filters

from .models import ActivityAction, ActivityEntityType, ActivityLog


class ActivityLogFilter(django_filters.FilterSet):
    business_date = django_filters.DateFilter(field_name="business_date")
    business_date__gte = django_filters.DateFilter(
        field_name="business_date", lookup_expr="gte"
    )
    business_date__lte = django_filters.DateFilter(
        field_name="business_date", lookup_expr="lte"
    )
    created_at__gte = django_filters.IsoDateTimeFilter(
        field_name="created_at", lookup_expr="gte"
    )
    created_at__lte = django_filters.IsoDateTimeFilter(
        field_name="created_at", lookup_expr="lte"
    )
    reviewed = django_filters.BooleanFilter(method="filter_reviewed")
    action = django_filters.ChoiceFilter(choices=ActivityAction.choices)
    entity_type = django_filters.ChoiceFilter(choices=ActivityEntityType.choices)

    class Meta:
        model = ActivityLog
        fields = [
            "site",
            "labour",
            "actor",
            "entity_type",
            "entity_id",
            "action",
            "business_date",
        ]

    def filter_reviewed(self, queryset, name, value):
        if value is True:
            return queryset.filter(reviewed_at__isnull=False)
        if value is False:
            return queryset.filter(reviewed_at__isnull=True)
        return queryset
