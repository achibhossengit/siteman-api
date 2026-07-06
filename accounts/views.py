from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenBlacklistView
from core import notifications, verifications
from company.models import Company
from .models import User
from .serializers import (
    # registration serializers
    RegisterConfirmSerializer,
    RegisterSerializer,
    ResendOtpSerializer,
    UserProfileSerializer,

    # token serializers
    CookieTokenObtainPairSerializer,
    CookieTokenRefreshSerializer,
    CookieTokenBlacklistSerializer,
)

REGISTER_PURPOSE = "register"
COMPANY_ADMIN_GROUP = "Company Admin"

def _set_refresh_token_cookie(response, refresh_token=None):
    if refresh_token is not None:
        response.set_cookie(
            key=getattr(settings, "AUTH_COOKIE_REFRESH", "refresh_token"),
            value=str(refresh_token),
            max_age=int(jwt_settings.REFRESH_TOKEN_LIFETIME.total_seconds()),
            httponly=True,
            secure=getattr(settings, "AUTH_COOKIE_SECURE", not settings.DEBUG),
            samesite=getattr(settings, "AUTH_COOKIE_SAMESITE", "Lax"),
            path=getattr(settings, "AUTH_COOKIE_PATH", "/api/v1/auth/token"),
        )

def _clear_refresh_token_cookie(response):
    response.delete_cookie(
        key=getattr(settings, "AUTH_COOKIE_REFRESH", "refresh_token"),
        path=getattr(settings, "AUTH_COOKIE_PATH", "/api/v1/auth/token"),
    )


def _register_otp_response(ticket, status_code=status.HTTP_200_OK):
    data = {
        "ticket": ticket,
        "otp_expires_in": verifications.OTP_AGE,
        "resend_cooldown": verifications.RESEND_COOLDOWN,
    }
    
    return Response(data, status=status_code)
     

# Using GenericAPIView instead of APIView so that DRF's Browsable API 
# can automatically detect the serializer_class and render the HTML input form.
class RegisterView(GenericAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer
    throttle_scope = "register"

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        payload = {
            "name": data["name"],
            "phone_number": data["phone_number"],
            "company_name": data["company_name"],
            "password": make_password(data["password"]),
            "email": data.get("email") or None,
            "channel": data["channel"],
        }
        
        ticket, delivery_info = verifications.create_ticket(
            purpose=REGISTER_PURPOSE,
            channel=payload["channel"],
            phone=data["phone_number"],
            email=payload["email"],
            payload=payload,
        )

        notifications.deliver_otp(**delivery_info)
        response = _register_otp_response(ticket, status_code=status.HTTP_201_CREATED)
        return response


class RegisterResendOtpView(GenericAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = ResendOtpSerializer
    throttle_scope = "register"

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = serializer.validated_data["ticket"]
        delivery_info = verifications.resend(ticket, purpose=REGISTER_PURPOSE)

        notifications.deliver_otp(**delivery_info)
        response = _register_otp_response(ticket, status_code=status.HTTP_200_OK)        
        return response


class RegisterConfirmView(GenericAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = RegisterConfirmSerializer
    throttle_scope = "register"

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = verifications.verify(
            serializer.validated_data["ticket"],
            serializer.validated_data["otp"],
            purpose=REGISTER_PURPOSE,
        )
        try:
            user = self._confirm_registration(payload)
        except IntegrityError:
            raise ValidationError(code="already_registered", detail={"phone_number": "This phone number is already registered."})
        serialized_user = UserProfileSerializer(user)
        return Response(data=serialized_user.data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def _confirm_registration(self, payload):
        # TODO: seed available Free-plan subscription here (endpoints.md F1 confirm) — blocked on subscription app.
        # TODO: auto-create CompanyConfig with built-in defaults (F3.5) — blocked on CompanyConfig model.
        company = Company.objects.create(name=payload["company_name"])
        user = User(
            name=payload["name"],
            phone_number=payload["phone_number"],
            email=payload["email"],
            company=company,
            is_active=True,
            is_staff=False,
        )
        user.password = payload["password"]
        user.save()
        admin_group, _ = Group.objects.get_or_create(name=COMPANY_ADMIN_GROUP)
        user.groups.add(admin_group)
        return user


class CookieTokenObtainPairView(TokenObtainPairView):
    serializer_class = CookieTokenObtainPairSerializer
    throttle_scope = "login"

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        _set_refresh_token_cookie(response, response.data["refresh"])
        return response


class CookieTokenRefreshView(TokenRefreshView):
    serializer_class = CookieTokenRefreshSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        # response contains 'refresh' only when ROTATE_REFRESH_TOKENS=True
        _set_refresh_token_cookie(response, response.data.get("refresh"))
        return response


class CookieTokenBlacklistView(TokenBlacklistView):
    serializer_class = CookieTokenBlacklistSerializer

    def post(self, request, *args, **kwargs):
        try:
            response = super().post(request, *args, **kwargs)
        except InvalidToken:
            response = Response({"detail": "Refresh token already invalid."})
        _clear_refresh_token_cookie(response)
        return response
    
