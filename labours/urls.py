from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import (
    LabourAttendanceViewSet,
    LabourPaymentViewSet,
    LabourViewSet,
    SiteLabourPaymentViewSet,
)

router = SimpleRouter(trailing_slash=False)
router.register("labours", LabourViewSet, basename="labour")

payments_router = SimpleRouter(trailing_slash=False)
payments_router.register("payments", LabourPaymentViewSet, basename="labour-payment")
payments_router.register(
    "attendances", LabourAttendanceViewSet, basename="labour-attendance"
)

site_payments_router = SimpleRouter(trailing_slash=False)
site_payments_router.register(
    "labour-payments", SiteLabourPaymentViewSet, basename="site-labour-payment"
)

urlpatterns = [
    *router.urls,
    path("labours/<int:labour_pk>/", include(payments_router.urls)),
    path("sites/<int:site_pk>/", include(site_payments_router.urls)),
]
