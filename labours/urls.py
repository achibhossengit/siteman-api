from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import (
    LabourAttendanceViewSet,
    LabourPaymentViewSet,
    LabourSessionDetailViewSet,
    LabourSessionViewSet,
    LabourViewSet,
    SiteLabourAttendanceViewSet,
    SiteLabourPaymentViewSet,
)

router = SimpleRouter(trailing_slash=False)
router.register("labours", LabourViewSet, basename="labour")

payments_router = SimpleRouter(trailing_slash=False)
payments_router.register("payments", LabourPaymentViewSet, basename="labour-payment")
payments_router.register(
    "attendances", LabourAttendanceViewSet, basename="labour-attendance"
)
payments_router.register(
    "sessions", LabourSessionViewSet, basename="labour-session"
)

session_details_router = SimpleRouter(trailing_slash=False)
session_details_router.register(
    "details", LabourSessionDetailViewSet, basename="labour-session-details"
)

site_payments_router = SimpleRouter(trailing_slash=False)
site_payments_router.register(
    "labour-payments", SiteLabourPaymentViewSet, basename="site-labour-payment"
)
site_payments_router.register(
    "labour-attendances",
    SiteLabourAttendanceViewSet,
    basename="site-labour-attendance",
)

urlpatterns = [
    *router.urls,
    path("labours/<int:labour_pk>/", include(payments_router.urls)),
    path(
        "labours/<int:labour_pk>/sessions/<int:session_pk>/",
        include(session_details_router.urls),
    ),
    path("sites/<int:site_pk>/", include(site_payments_router.urls)),
]
