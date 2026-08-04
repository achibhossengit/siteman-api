from rest_framework_nested import routers

from .views import ActivityLogViewSet

router = routers.SimpleRouter(trailing_slash=False)
router.register("activities", ActivityLogViewSet, basename="activity")

urlpatterns = [
    *router.urls,
]
