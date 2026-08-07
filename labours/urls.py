from rest_framework_nested import routers

from .views import (
    DailyRecordViewSet,
    LabourSessionViewSet,
    LabourViewSet,
)

router = routers.SimpleRouter(trailing_slash=False)
router.register("labours", LabourViewSet, basename="labour")

labours_router = routers.NestedSimpleRouter(router, "labours", lookup="labour")
labours_router.register(
    "daily-records", DailyRecordViewSet, basename="labour-daily-record"
)
labours_router.register("sessions", LabourSessionViewSet, basename="labour-session")

urlpatterns = [
    *router.urls,
    *labours_router.urls,
]
