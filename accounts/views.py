from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from core import notifications, verifications
from company.models import Company
from .models import User
from .serializers import RegisterConfirmSerializer, RegisterSerializer, ResendOtpSerializer, UserProfileSerializer

REGISTER_PURPOSE = "register"
COMPANY_ADMIN_GROUP = "Company Admin"

def _register_otp_response(ticket, delivery_info, status_code=status.HTTP_200_OK):
    data = {
        "ticket": ticket,
        "otp_expires_in": verifications.OTP_AGE,
        "resend_cooldown": verifications.RESEND_COOLDOWN,
    }
    
    notifications.deliver_otp(**delivery_info)
    return Response(data, status=status_code)
     

# Using GenericAPIView instead of APIView so that DRF's Browsable API 
# can automatically detect the serializer_class and render the HTML input form.
class RegisterView(GenericAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer
    throttle_scope = "register"

    def post(self, request):
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
        
        return _register_otp_response(ticket, delivery_info, status_code=status.HTTP_201_CREATED)


class RegisterResendOtpView(GenericAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = ResendOtpSerializer
    throttle_scope = "register"

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = serializer.validated_data["ticket"]

        delivery_info = verifications.resend(ticket, purpose=REGISTER_PURPOSE)
        
        return _register_otp_response(ticket, delivery_info, status_code=status.HTTP_200_OK)


class RegisterConfirmView(GenericAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = RegisterConfirmSerializer
    throttle_scope = "register"

    def post(self, request):
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
        # TODO: auto-login after registration
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
