from django.urls import path
from .views import (
    RegisterView, 
    RegisterResendOtpView, 
    RegisterConfirmView, 
    CookieTokenObtainPairView, 
    CookieTokenRefreshView, 
    CookieTokenBlacklistView,
)

urlpatterns = [
    path("register", RegisterView.as_view(), name="register"),
    path("register/resend-otp", RegisterResendOtpView.as_view(), name="register-resend-otp"),
    path("register/confirm", RegisterConfirmView.as_view(), name="register-confirm"),

    path("token/obtain", CookieTokenObtainPairView.as_view(), name="token-obtain"),
    path("token/refresh", CookieTokenRefreshView.as_view(), name="token-refresh"),
    path("token/blacklist", CookieTokenBlacklistView.as_view(), name="token-blacklist"),
]
