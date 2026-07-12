from rest_framework.routers import SimpleRouter

from .views import LabourViewSet

router = SimpleRouter(trailing_slash=False)
router.register("labours", LabourViewSet, basename="labour")

urlpatterns = router.urls
