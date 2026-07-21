from rest_framework_nested import routers

from labours.views import SiteLabourAttendanceViewSet, SiteLabourPaymentViewSet

from .views import PrivateSiteCashViewSet, SiteCashViewSet, SiteViewSet

router = routers.SimpleRouter(trailing_slash=False)
router.register("sites", SiteViewSet, basename="site")

# Parent SiteViewSet uses default lookup ``pk`` → nested kwarg is ``site_pk``.
sites_router = routers.NestedSimpleRouter(router, "sites", lookup="site")
sites_router.register("cash", SiteCashViewSet, basename="site-cash")
sites_router.register(
    "private-cash", PrivateSiteCashViewSet, basename="site-private-cash"
)
sites_router.register(
    "labour-payments", SiteLabourPaymentViewSet, basename="site-labour-payment"
)
sites_router.register(
    "labour-attendances",
    SiteLabourAttendanceViewSet,
    basename="site-labour-attendance",
)

urlpatterns = [
    *router.urls,
    *sites_router.urls,
]
