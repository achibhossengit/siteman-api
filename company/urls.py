from django.urls import path

from .views import CompanyViewSet

urlpatterns = [
    path(
        "company",
        CompanyViewSet.as_view({"patch": "partial_update", "delete": "destroy"}),
        name="company-detail",
    ),
]
