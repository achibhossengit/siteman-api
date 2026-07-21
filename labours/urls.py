from rest_framework_nested import routers

from .views import (
    LabourAttendanceViewSet,
    LabourPaymentViewSet,
    LabourSessionDetailViewSet,
    LabourSessionViewSet,
    LabourViewSet,
)

router = routers.SimpleRouter(trailing_slash=False)
router.register("labours", LabourViewSet, basename="labour")

labours_router = routers.NestedSimpleRouter(router, "labours", lookup="labour")
labours_router.register("payments", LabourPaymentViewSet, basename="labour-payment")
labours_router.register(
    "attendances", LabourAttendanceViewSet, basename="labour-attendance"
)
labours_router.register("sessions", LabourSessionViewSet, basename="labour-session")

sessions_router = routers.NestedSimpleRouter(
    labours_router, "sessions", lookup="session"
)
sessions_router.register(
    "details", LabourSessionDetailViewSet, basename="labour-session-details"
)

urlpatterns = [
    *router.urls,
    *labours_router.urls,
    *sessions_router.urls,
]
