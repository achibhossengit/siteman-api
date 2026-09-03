from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.serializers import TokenBlacklistSerializer, TokenObtainPairSerializer, TokenRefreshSerializer
from core import status_codes
from core.images import ProfilePhotoField
from core.phone import format_bd_phone_local, normalize_bd_phone
from sites.models import Site
from .models import GroupProfile, UserSite

User = get_user_model()
OTP_LENGTH = getattr(settings, "OTP_LENGTH", 6)


# ============= Auth serializers =============
class BDPhoneNumberField(serializers.CharField):
    """Store as +880…; serialize responses as 01XXXXXXXXX."""

    def to_representation(self, value):
        return format_bd_phone_local(value)


class RegisterSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    phone_number = serializers.CharField(max_length=20)
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



# ============= User serializers =============
def _get_site_ids_for_user(user):
    if user.is_companyadmin:
        return list(
            Site.objects.filter(company_id=user.company_id).values_list(
                "id", flat=True
            )
        )
    return list(
        UserSite.objects.filter(user_id=user.pk).values_list("site_id", flat=True)
    )


def _get_tenant_sites_for_request(serializer):
    request = serializer.context.get("request")
    company_id = getattr(getattr(request, "user", None), "company_id", None)
    if company_id is None:
        return Site.objects.none()
    return Site.objects.filter(company_id=company_id)


def _set_user_groups_and_sites(instance, groups, sites, company):
    if groups is not None:
        instance.groups.set(groups)
    if sites is not None:
        sites_by_id = {site.pk: site for site in sites}
        instance.sites.exclude(site_id__in=sites_by_id).delete()
        existing_site_ids = set(instance.sites.values_list("site_id", flat=True))
        for site_id, site in sites_by_id.items():
            if site_id not in existing_site_ids:
                UserSite.objects.create(
                    user=instance,
                    site=site,
                    company=company,
                )
    return instance


def _validate_unique_user_phone(phone, exclude_pk=None):
    try:
        phone = normalize_bd_phone(phone)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(exc.messages[0])
    qs = User.objects.filter(phone_number=phone)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    if qs.exists():
        raise serializers.ValidationError(
            "This phone number is already registered.",
            code=status_codes.ALREADY_REGISTERED,
        )
    return phone


def _validate_unique_user_name(name, company_id, exclude_pk=None):
    if company_id is None:
        return name
    qs = User.objects.filter(company_id=company_id, name=name)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    if qs.exists():
        raise serializers.ValidationError(
            "A user with this name already exists in your company.",
            code=status_codes.USER_NAME_EXISTS,
        )
    return name


class UserSiteRelatedField(serializers.PrimaryKeyRelatedField):
    def to_representation(self, value):
        return value.site_id


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


class UserDetailSerializer(serializers.ModelSerializer):
    """Company user retrieve: identity plus assigned groups. No company payload."""

    allowed_groups = serializers.SerializerMethodField()
    allowed_sites = serializers.SerializerMethodField()
    phone_number = BDPhoneNumberField(read_only=True)
    photo = ProfilePhotoField(read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "name",
            "photo",
            "phone_number",
            "email",
            "is_active",
            "is_staff",
            "is_companyadmin",
            "allowed_groups",
            "allowed_sites",
        )
        read_only_fields = fields

    def get_allowed_groups(self, obj):
        return list(obj.groups.values_list("id", flat=True))

    def get_allowed_sites(self, obj):
        return _get_site_ids_for_user(obj)


class UserCreateSerializer(serializers.ModelSerializer):
    """Create a company user with an initial password set by the admin.

    Password is write-only and create-only. Updates go through
    ``UserUpdateSerializer``, which does not accept password — users change
    their own password via ``/auth/password/change`` or reset.

    Optional ``groups`` (tenant group ids) and ``allowed_sites`` (site ids)
    are assigned in the same request.
    """

    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    phone_number = BDPhoneNumberField()
    groups = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=GroupProfile.tenant_groups(),
        required=False,
    )
    allowed_sites = UserSiteRelatedField(
        many=True,
        queryset=Site.objects.none(),
        required=False,
        source="sites",
    )

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
            "groups",
            "allowed_sites",
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
            "phone_number": {"validators": []},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance is None:
            self.fields["is_active"].read_only = True
        self.fields["allowed_sites"].child_relation.queryset = (
            _get_tenant_sites_for_request(self)
        )

    def validate_phone_number(self, value):
        exclude_pk = self.instance.pk if self.instance is not None else None
        return _validate_unique_user_phone(value, exclude_pk=exclude_pk)

    def validate_name(self, value):
        exclude_pk = self.instance.pk if self.instance is not None else None
        return _validate_unique_user_name(
            value,
            self.context["request"].user.company_id,
            exclude_pk=exclude_pk,
        )

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        groups = validated_data.pop("groups", None)
        sites = validated_data.pop("sites", None)
        user = User.objects.create_user(password=password, **validated_data)
        return _set_user_groups_and_sites(
            user, groups, sites, self.context["request"].user.company
        )


class UserUpdateSerializer(serializers.ModelSerializer):
    groups = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=GroupProfile.tenant_groups(),
        required=False,
    )
    allowed_sites = UserSiteRelatedField(
        many=True,
        queryset=Site.objects.none(),
        required=False,
        source="sites",
    )

    class Meta:
        model = User
        fields = ["id", "is_active", "groups", "allowed_sites"]
        read_only_fields = ["id"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["allowed_sites"].child_relation.queryset = (
            _get_tenant_sites_for_request(self)
        )

    def update(self, instance, validated_data):
        groups = validated_data.pop("groups", None)
        sites = validated_data.pop("sites", None)
        instance = super().update(instance, validated_data)
        return _set_user_groups_and_sites(
            instance, groups, sites, self.context["request"].user.company
        )


class UserDeleteSerializer(serializers.Serializer):
    """Confirm the acting admin's password before hard-deleting a user."""

    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Password is incorrect.")
        return value


# ============= Profile serializers =============
class ProfileDetailSerializer(serializers.ModelSerializer):
    """GET /profile: identity plus access snapshot."""

    allowed_permissions = serializers.SerializerMethodField()
    allowed_sites = serializers.SerializerMethodField()
    phone_number = BDPhoneNumberField(read_only=True)
    photo = ProfilePhotoField(read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "name",
            "photo",
            "phone_number",
            "email",
            "is_active",
            "is_staff",
            "is_companyadmin",
            "allowed_permissions",
            "allowed_sites",
        )
        read_only_fields = fields

    def get_allowed_permissions(self, obj):
        return sorted(obj.get_all_permissions())

    def get_allowed_sites(self, obj):
        return _get_site_ids_for_user(obj)


class ProfileUpdateSerializer(serializers.ModelSerializer):
    """PATCH /profile: name, photo, phone, email."""

    phone_number = BDPhoneNumberField()
    photo = ProfilePhotoField(required=False, allow_null=True)

    class Meta:
        model = User
        fields = ("name", "photo", "phone_number", "email")
        extra_kwargs = {
            "phone_number": {"validators": []},
        }

    def validate_phone_number(self, value):
        exclude_pk = self.instance.pk if self.instance is not None else None
        return _validate_unique_user_phone(value, exclude_pk=exclude_pk)

    def validate_name(self, value):
        exclude_pk = self.instance.pk if self.instance is not None else None
        return _validate_unique_user_name(
            value,
            getattr(self.instance, "company_id", None),
            exclude_pk=exclude_pk,
        )


