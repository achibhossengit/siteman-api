from django.urls import path
from rest_framework_nested import routers

from .views import (
    RegisterView,
    RegisterResendOtpView,
    RegisterConfirmView,
    PasswordResetView,
    PasswordResetResendOtpView,
    PasswordResetConfirmView,
    PasswordChangeView,
    CookieTokenObtainPairView,
    CookieTokenRefreshView,
    CookieTokenBlacklistView,
    UserGroupViewSet,
    UserSiteViewSet,
    UserViewSet,
)

router = routers.SimpleRouter(trailing_slash=False)
router.register("users", UserViewSet, basename="user")

users_router = routers.NestedSimpleRouter(router, "users", lookup="user")
users_router.register("groups", UserGroupViewSet, basename="user-group")
users_router.register("sites", UserSiteViewSet, basename="user-site")

urlpatterns = [
    path("auth/register", RegisterView.as_view(), name="register"),
    path("auth/register/resend-otp", RegisterResendOtpView.as_view(), name="register-resend-otp"),
    path("auth/register/confirm", RegisterConfirmView.as_view(), name="register-confirm"),

    path("auth/password/reset", PasswordResetView.as_view(), name="password-reset"),
    path(
        "auth/password/reset/resend-otp",
        PasswordResetResendOtpView.as_view(),
        name="password-reset-resend-otp",
    ),
    path(
        "auth/password/reset/confirm",
        PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    path("auth/password/change", PasswordChangeView.as_view(), name="password-change"),

    path("auth/token/obtain", CookieTokenObtainPairView.as_view(), name="token-obtain"),
    path("auth/token/refresh", CookieTokenRefreshView.as_view(), name="token-refresh"),
    path("auth/token/blacklist", CookieTokenBlacklistView.as_view(), name="token-blacklist"),

    *router.urls,
    *users_router.urls,
]
