from rest_framework_nested import routers

from .views import (
    LabourAttendanceViewSet,
    LabourPaymentViewSet,
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

urlpatterns = [
    *router.urls,
    *labours_router.urls,
]
