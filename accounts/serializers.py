import secrets

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
from sites.models import Site
from .models import UserSite

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
    """Own profile: GET returns full snapshot; PATCH updates basic fields.

    Writable: name, email, phone_number.
    Password changes go through ``/auth/password/change`` or reset.
    """

    company = serializers.SerializerMethodField()
    groups = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    sites = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "name",
            "phone_number",
            "email",
            "company",
            "is_active",
            "is_staff",
            "is_companyadmin",
            "groups",
            "permissions",
            "sites",
        )
        read_only_fields = (
            "id",
            "company",
            "is_active",
            "is_staff",
            "is_companyadmin",
            "groups",
            "permissions",
            "sites",
        )
        extra_kwargs = {
            "phone_number": {"validators": []},
        }

    def get_company(self, obj):
        if obj.company_id is None:
            return None
        return {"id": obj.company_id, "name": obj.company.name}

    def get_groups(self, obj):
        return [
            {"id": group.pk, "name": group.name}
            for group in obj.groups.all().order_by("name")
        ]

    def get_permissions(self, obj):
        return sorted(obj.get_all_permissions())

    def get_sites(self, obj):
        assignments = (
            obj.sites.select_related("site")
            .order_by("site__name", "id")
        )
        return [
            {
                "id": assignment.site_id,
                "name": assignment.site.name,
                "is_active": assignment.site.is_active,
                "is_closed": assignment.site.is_closed,
            }
            for assignment in assignments
        ]

    def validate_phone_number(self, value):
        try:
            phone = normalize_bd_phone(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages[0])
        qs = User.objects.filter(phone_number=phone)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "This phone number is already registered.",
                code=status_codes.ALREADY_REGISTERED,
            )
        return phone

    def validate_name(self, value):
        company_id = getattr(self.instance, "company_id", None)
        if company_id is None:
            return value
        qs = User.objects.filter(company_id=company_id, name=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "A user with this name already exists in your company.",
                code=status_codes.USER_NAME_EXISTS,
            )
        return value


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


class UserCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "name",
            "phone_number",
            "email",
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
        if self.instance is None:
            # Create always stamps is_active=True in the viewset.
            self.fields["is_active"].read_only = True

    def validate_phone_number(self, value):
        try:
            phone = normalize_bd_phone(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages[0])
        qs = User.objects.filter(phone_number=phone)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
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

    def create(self, validated_data):
        # Unknown to the creator; first login uses forgot-password reset.
        password = secrets.token_urlsafe(32)
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


class UserSiteRelatedField(serializers.PrimaryKeyRelatedField):
    def to_representation(self, value):
        return value.site_id


class UserUpdateSerializer(serializers.ModelSerializer):
    groups = UserGroupSerializer(many=True, required=False)
    sites = UserSiteRelatedField(
        many=True,
        queryset=Site.objects.none(),
        required=False,
    )

    class Meta:
        model = User
        fields = ["id", "is_active", "groups", "sites"]
        read_only_fields = ["id"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        company_id = getattr(getattr(request, "user", None), "company_id", None)
        if company_id is not None:
            self.fields["sites"].child_relation.queryset = Site.objects.filter(
                company_id=company_id
            )

    def update(self, instance, validated_data):
        groups_data = validated_data.pop("groups", None)
        sites = validated_data.pop("sites", None)
        instance = super().update(instance, validated_data)

        if groups_data is not None:
            instance.groups.set(group_data["id"] for group_data in groups_data)

        if sites is not None:
            sites_by_id = {site.pk: site for site in sites}
            instance.sites.exclude(site_id__in=sites_by_id).delete()
            existing_site_ids = set(
                instance.sites.values_list("site_id", flat=True)
            )
            request = self.context["request"]
            for site_id, site in sites_by_id.items():
                if site_id not in existing_site_ids:
                    UserSite.objects.create(
                        user=instance,
                        site=site,
                        company=request.user.company,
                        created_by=request.user,
                    )

        return instance


class UserSiteSerializer(serializers.ModelSerializer):
    """List/create under ``/users/<user_pk>/sites`` (body: ``site``)."""

    class Meta:
        model = UserSite
        fields = ["id", "user", "site", "created_at", "updated_at"]
        read_only_fields = ["id", "user", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        company_id = getattr(getattr(request, "user", None), "company_id", None)
        if company_id is not None and "site" in self.fields:
            self.fields["site"].queryset = Site.objects.filter(company_id=company_id)


class SiteUserSerializer(serializers.ModelSerializer):
    """List/create under ``/sites/<site_pk>/users`` (body: ``user``)."""

    class Meta:
        model = UserSite
        fields = ["id", "user", "site", "created_at", "updated_at"]
        read_only_fields = ["id", "site", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        company_id = getattr(getattr(request, "user", None), "company_id", None)
        if company_id is not None and "user" in self.fields:
            self.fields["user"].queryset = User.objects.filter(
                company_id=company_id,
                deleted_at__isnull=True,
            )


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

