from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.serializers import TokenBlacklistSerializer, TokenObtainPairSerializer, TokenRefreshSerializer
from core import status_codes
from core.phone import format_bd_phone_local, normalize_bd_phone
from sites.models import Site
from sites.serializers import SiteListSerializer
from .models import UserSite

User = get_user_model()
OTP_LENGTH = getattr(settings, "OTP_LENGTH", 6)

# Allowed group names for company users.
ROLE_GROUP_NAMES = (
    # "Company Admin",
    "Site Manager",
    "Site Auditor",
)


class BDPhoneNumberField(serializers.CharField):
    """Store as +880…; serialize responses as 01XXXXXXXXX."""

    def to_representation(self, value):
        return format_bd_phone_local(value)


class RegisterSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    phone_number = serializers.CharField(max_length=20)
    email = serializers.EmailField(required=True, allow_blank=False)
    company_name = serializers.CharField(max_length=255)
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

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

    Writable: name and phone_number. Email changes require a verification flow.
    Password changes go through ``/auth/password/change`` or reset.

    ``allowed_*`` is this user's access. ``sites`` is the company site catalog
    (id → name and related fields), not the access list.
    """

    company = serializers.SerializerMethodField()
    allowed_groups = serializers.SerializerMethodField()
    allowed_permissions = serializers.SerializerMethodField()
    allowed_sites = serializers.SerializerMethodField()
    sites = serializers.SerializerMethodField()
    phone_number = BDPhoneNumberField()

    class Meta:
        model = User
        fields = (
            "id",
            "name",
            "photo",
            "phone_number",
            "email",
            "company",
            "is_active",
            "is_staff",
            "is_companyadmin",
            "allowed_groups",
            "allowed_permissions",
            "allowed_sites",
            "sites",
        )
        read_only_fields = (
            "id",
            "company",
            "is_active",
            "is_staff",
            "is_companyadmin",
            "allowed_groups",
            "allowed_permissions",
            "allowed_sites",
            "sites",
        )
        extra_kwargs = {
            "phone_number": {"validators": []},
            "photo": {"required": False, "allow_null": True},
        }

    def get_company(self, obj):
        if obj.company_id is None:
            return None
        return {"id": obj.company_id, "name": obj.company.name}

    def get_allowed_groups(self, obj):
        return [
            {"id": group.pk, "name": group.name}
            for group in obj.groups.all().order_by("name")
        ]

    def get_allowed_permissions(self, obj):
        return sorted(obj.get_all_permissions())

    def get_allowed_sites(self, obj):
        if obj.is_companyadmin and obj.company_id is not None:
            return list(
                Site.objects.filter(company_id=obj.company_id).values_list(
                    "id", flat=True
                )
            )
        return list(obj.sites.values_list("site_id", flat=True))

    def get_sites(self, obj):
        if obj.company_id is None:
            return []
        qs = Site.objects.filter(company_id=obj.company_id).order_by("name", "id")
        return SiteListSerializer(qs, many=True).data

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
    phone_number = BDPhoneNumberField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "name",
            "photo",
            "phone_number",
            "email",
            "is_active",
            "is_companyadmin",
        ]


class UserCreateSerializer(serializers.ModelSerializer):
    """Create a company user with an initial password set by the admin.

    Password is write-only and create-only. Updates go through
    ``UserUpdateSerializer``, which does not accept password — users change
    their own password via ``/auth/password/change`` or reset.
    """

    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    phone_number = BDPhoneNumberField()

    class Meta:
        model = User
        fields = [
            "id",
            "name",
            "phone_number",
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

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        return User.objects.create_user(password=password, **validated_data)


class UserGroupRelatedField(serializers.SlugRelatedField):
    def to_representation(self, instance):
        return {"id": instance.pk, "name": instance.name}


class UserSiteRelatedField(serializers.PrimaryKeyRelatedField):
    def to_representation(self, value):
        return value.site_id


class UserUpdateSerializer(serializers.ModelSerializer):
    groups = UserGroupRelatedField(
        many=True,
        slug_field="name",
        queryset=Group.objects.filter(name__in=ROLE_GROUP_NAMES),
        required=False,
    )
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

    def validate_groups(self, groups):
        if len(groups) > 1:
            raise serializers.ValidationError(
                "A user can belong to only one group at a time.",
                code=status_codes.INVALID,
            )
        return groups

    def update(self, instance, validated_data):
        groups = validated_data.pop("groups", None)
        sites = validated_data.pop("sites", None)
        instance = super().update(instance, validated_data)

        if groups is not None:
            instance.groups.set(groups)

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
                    )

        return instance


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

