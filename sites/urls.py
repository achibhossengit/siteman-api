from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import PrivateSiteCashViewSet, SiteCashViewSet, SiteViewSet

router = SimpleRouter(trailing_slash=False)
router.register("sites", SiteViewSet, basename="site")

cash_router = SimpleRouter(trailing_slash=False)
cash_router.register("cash", SiteCashViewSet, basename="site-cash")
cash_router.register(
    "private-cash", PrivateSiteCashViewSet, basename="site-private-cash"
)

urlpatterns = [
    *router.urls,
    path("sites/<int:site_pk>/", include(cash_router.urls)),
]
