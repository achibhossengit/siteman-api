from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import LabourPaymentViewSet, LabourViewSet

router = SimpleRouter(trailing_slash=False)
router.register("labours", LabourViewSet, basename="labour")

payments_router = SimpleRouter(trailing_slash=False)
payments_router.register("payments", LabourPaymentViewSet, basename="labour-payment")

urlpatterns = [
    *router.urls,
    path("labours/<int:labour_pk>/", include(payments_router.urls)),
]
