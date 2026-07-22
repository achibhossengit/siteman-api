from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.serializers import TokenBlacklistSerializer, TokenObtainPairSerializer, TokenRefreshSerializer
from core import status_codes
from core.phone import normalize_bd_phone

User = get_user_model()
OTP_LENGTH = getattr(settings, "OTP_LENGTH", 6)
REGISTER_PURPOSE = "register"

# Roles created in accounts.0003_create_groups.
ROLE_GROUP_NAMES = (
    "Company Admin",
    "Site Manager",
    "Site Auditor",
)


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
                code=status_codes.REQUIRED_EMAIL, detail={"email": "Email channel requires an email address."}
            )
        return attrs

    def validate_phone_number(self, value):
        try:
            phone = normalize_bd_phone(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages[0])
        if User.objects.filter(phone_number=phone).exists():
            raise serializers.ValidationError(code=status_codes.ALREADY_REGISTERED, detail="This phone number is already registered.")
        return phone

    def validate_password(self, value):
        validate_password(value)
        return value


class ResendOtpSerializer(serializers.Serializer):
    ticket = serializers.CharField(max_length=255)


class RegisterConfirmSerializer(serializers.Serializer):
    ticket = serializers.CharField(max_length=255)
    otp = serializers.CharField(max_length=OTP_LENGTH, min_length=OTP_LENGTH)


class PasswordResetSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20)
    name = serializers.CharField(max_length=255)

    def validate_phone_number(self, value):
        # format check only — existence is never validated here, so the
        # response can not leak which numbers are registered
        try:
            return normalize_bd_phone(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages[0])


class PasswordResetConfirmSerializer(serializers.Serializer):
    ticket = serializers.CharField(max_length=255)
    otp = serializers.CharField(max_length=OTP_LENGTH, min_length=OTP_LENGTH)
    new_password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_new_password(self, value):
        validate_password(value)
        return value


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, style={"input_type": "password"})
    new_password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_current_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value):
        validate_password(value, user=self.context["request"].user)
        return value
    

class UserProfileSerializer(serializers.ModelSerializer):
    company = serializers.SerializerMethodField()
    groups = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "name",
            "phone_number",
            "email",
            "company",
            "groups",
            "is_staff",
            "is_companyadmin",
        )

    def get_company(self, obj):
        if obj.company_id is None:
            return None
        return {"id": obj.company_id, "name": obj.company.name}

    def get_groups(self, obj):
        return list(obj.groups.values_list("name", flat=True))


class UserListSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "name",
            "phone_number",
            "email",
            "is_active",
            "is_companyadmin",
        ]


class UserSerializer(serializers.ModelSerializer):
    """Create / retrieve / partial update.

    Phone and password are create-only; patch may change name, email, is_active.
    """

    password = serializers.CharField(
        write_only=True,
        required=False,
        style={"input_type": "password"},
    )

    class Meta:
        model = User
        fields = [
            "id",
            "name",
            "phone_number",
            "email",
            "password",
            "is_active",
            "is_companyadmin",
            "company",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "is_companyadmin",
            "company",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            # Own uniqueness check → ALREADY_REGISTERED (after normalize).
            "phone_number": {"validators": []},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance is not None:
            # Patch: phone/password immutable; is_active writable for activate/deactivate.
            self.fields["phone_number"].read_only = True
            self.fields.pop("password", None)
        else:
            self.fields["password"].required = True
            # Create always stamps is_active=True in the viewset.
            self.fields["is_active"].read_only = True

    def validate_phone_number(self, value):
        try:
            phone = normalize_bd_phone(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages[0])
        if User.objects.filter(phone_number=phone).exists():
            raise serializers.ValidationError(
                "This phone number is already registered.",
                code=status_codes.ALREADY_REGISTERED,
            )
        return phone

    def validate_name(self, value):
        company = self.context["request"].user.company
        qs = User.objects.filter(company=company, name=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "A user with this name already exists in your company.",
                code=status_codes.USER_NAME_EXISTS,
            )
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        return User.objects.create_user(password=password, **validated_data)


class UserGroupSerializer(serializers.ModelSerializer):
    id = serializers.PrimaryKeyRelatedField(
        queryset=Group.objects.filter(name__in=ROLE_GROUP_NAMES),
    )

    class Meta:
        model = Group
        fields = ["id", "name"]
        read_only_fields = ["name"]

    def to_representation(self, instance):
        return {"id": instance.pk, "name": instance.name}


class CookieTokenObtainPairSerializer(TokenObtainPairSerializer):
    
    def validate_phone_number(self, value):
        phone = normalize_bd_phone(value)
        return phone


class CookieRefreshFallbackMixin:
    """Let `refresh` come from the request body or, failing that, the
    httponly auth cookie — browser clients cannot read the cookie from JS."""

    def validate(self, attrs):
        if not attrs.get("refresh"):
            request = self.context.get("request")
            cookie_name = getattr(settings, "REFRESH_TOKEN_COOKIE_NAME", "refresh_token")
            attrs["refresh"] = request.COOKIES.get(cookie_name) if request else None
        if not attrs["refresh"]:
            raise InvalidToken("No refresh token found in request body or cookie.")
        return super().validate(attrs)


class CookieTokenRefreshSerializer(CookieRefreshFallbackMixin, TokenRefreshSerializer):
    refresh = serializers.CharField(required=False)


class CookieTokenBlacklistSerializer(CookieRefreshFallbackMixin, TokenBlacklistSerializer):
    refresh = serializers.CharField(required=False, write_only=True)

