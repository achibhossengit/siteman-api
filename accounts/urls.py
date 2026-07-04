from django.urls import path
from .views import RegisterConfirmView, RegisterResendOtpView, RegisterView

urlpatterns = [
    path("register", RegisterView.as_view(), name="register"),
    path("register/resend-otp", RegisterResendOtpView.as_view(), name="register-resend-otp"),
    path("register/confirm", RegisterConfirmView.as_view(), name="register-confirm"),
]
