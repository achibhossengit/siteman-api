from rest_framework.routers import SimpleRouter

from .views import SiteViewSet

router = SimpleRouter(trailing_slash=False)
router.register("sites", SiteViewSet, basename="site")

urlpatterns = router.urls
