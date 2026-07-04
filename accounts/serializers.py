from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from core.phone import normalize_bd_phone

User = get_user_model()
OTP_LENGTH = getattr(settings, "OTP_LENGTH", 6)
REGISTER_PURPOSE = "register"


class RegisterSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    phone_number = serializers.CharField(max_length=20)
    email = serializers.EmailField(required=False, allow_blank=True)
    company_name = serializers.CharField(max_length=255)
    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    channel = serializers.ChoiceField(choices=("sms", "email"), default="sms")

    def validate(self, attrs):
        if attrs.get("channel") == "email" and not attrs.get("email"):
            # code= kwarg is dropped by DRF when detail is a dict; ErrorDetail keeps it.
            raise serializers.ValidationError(
                code= "required_email", detail={"email": "Email channel requires an email address."}
            )
        return attrs

    def validate_phone_number(self, value):
        try:
            phone = normalize_bd_phone(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages[0])
        if User.objects.filter(phone_number=phone).exists():
            raise serializers.ValidationError(code="already_registered", detail="This phone number is already registered.")
        return phone

    def validate_password(self, value):
        validate_password(value)
        return value


class ResendOtpSerializer(serializers.Serializer):
    ticket = serializers.CharField(max_length=255)


class RegisterConfirmSerializer(serializers.Serializer):
    ticket = serializers.CharField(max_length=255)
    otp = serializers.CharField(max_length=OTP_LENGTH, min_length=OTP_LENGTH)
    

class UserProfileSerializer(serializers.ModelSerializer):
    company = serializers.SerializerMethodField()
    groups = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "name", "phone_number", "email", "company", "groups", "is_staff")

    def get_company(self, obj):
        if obj.company_id is None:
            return None
        return {"id": obj.company_id, "name": obj.company.name}

    def get_groups(self, obj):
        return list(obj.groups.values_list("name", flat=True))