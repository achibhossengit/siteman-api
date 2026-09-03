from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.filters import SearchFilter
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenBlacklistView
from core import notifications, status_codes, verifications
from core.exceptions import (
    SubscriptionExpired,
    SubscriptionExpiredError,
    SubscriptionLimitExceeded,
    SubscriptionLimitExceededError,
)
from core.pagination import StandardPagination
from core.services import SubscriptionService
from company.models import Company
from .models import GroupProfile, User
from .serializers import (
    # registration serializers
    RegisterSerializer,
    ResendOtpSerializer,
    UserCreateSerializer,
    UserDetailSerializer,
    ProfileDetailSerializer,
    ProfileUpdateSerializer,

    # password reset serializers
    PasswordResetSerializer,
    PasswordResetConfirmSerializer,
    PasswordChangeSerializer,

    # token serializers
    CookieTokenObtainPairSerializer,
    CookieTokenRefreshSerializer,
    CookieTokenBlacklistSerializer,

    # company user management
    UserDeleteSerializer,
    UserListSerializer,
    UserUpdateSerializer,
)

PASSWORD_RESET_PURPOSE = "password_reset"


def _ensure_registration_enabled():
    if not settings.REGISTRATION_ENABLED:
        raise PermissionDenied(
            detail="Registration is temporarily unavailable.",
            code=status_codes.REGISTRATION_DISABLED,
        )


def _set_refresh_token_cookie(response, refresh_token=None):
    if refresh_token is not None:
        response.set_cookie(
            key=getattr(settings, "REFRESH_TOKEN_COOKIE_NAME", "refresh_token"),
            value=str(refresh_token),
            max_age=int(jwt_settings.REFRESH_TOKEN_LIFETIME.total_seconds()),
            httponly=True,
            secure=getattr(settings, "REFRESH_TOKEN_COOKIE_SECURE"),
            samesite=getattr(settings, "REFRESH_TOKEN_COOKIE_SAMESITE"),
            path=getattr(settings, "REFRESH_TOKEN_COOKIE_PATH", "/api/v1/auth/token"),
        )

def _clear_refresh_token_cookie(response):
    response.delete_cookie(
        key=getattr(settings, "REFRESH_TOKEN_COOKIE_NAME", "refresh_token"),
        path=getattr(settings, "REFRESH_TOKEN_COOKIE_PATH", "/api/v1/auth/token"),
        samesite=getattr(settings, "REFRESH_TOKEN_COOKIE_SAMESITE"),
    )


def _ticket_response(ticket, status_code=status.HTTP_200_OK):
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
        _ensure_registration_enabled()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = self._create_account(serializer.validated_data)
        except IntegrityError:
            raise ValidationError(
                code=status_codes.ALREADY_REGISTERED,
                detail={"phone_number": "This phone number is already registered."},
            )
        serialized_user = ProfileDetailSerializer(user)
        return Response(data=serialized_user.data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def _create_account(self, data):
        company = Company.objects.create(name=data["company_name"])
        user = User(
            name=data["name"],
            phone_number=data["phone_number"],
            company=company,
            is_active=True,
            is_staff=False,
            is_companyadmin=True,
        )
        user.password = make_password(data["password"])
        user.save()
        user.groups.set(GroupProfile.non_platform_groups())
        return user


class PasswordResetView(GenericAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = PasswordResetSerializer
    throttle_scope = "password_reset"

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = serializer.validated_data["phone_number"]

        # Anti-enumeration: a ticket is minted and the same 200 body returned
        # whether or not the phone is registered. Only a real, active account
        # with a stored email gets a deliverable contact, so
        # nothing is ever sent and its OTP can never be verified.
        user = User.objects.filter(
            phone_number=phone,
            is_active=True,
        ).first()
        ticket, delivery_info = verifications.create_ticket(
            purpose=PASSWORD_RESET_PURPOSE,
            email=user.email if user and user.email else None,
            payload={"user_id": user.id if user else None},
        )

        # Ghost tickets and legacy users without email have no deliverable contact.
        if delivery_info["email"]:
            notifications.deliver_otp(**delivery_info)
        return _ticket_response(ticket, status_code=status.HTTP_200_OK)


class PasswordResetResendOtpView(GenericAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = ResendOtpSerializer
    throttle_scope = "password_reset"

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = serializer.validated_data["ticket"]
        delivery_info = verifications.resend(ticket, purpose=PASSWORD_RESET_PURPOSE)

        # Ghost tickets and legacy users without email have no deliverable contact.
        if delivery_info["email"]:
            notifications.deliver_otp(**delivery_info)
        return _ticket_response(ticket, status_code=status.HTTP_200_OK)


class PasswordResetConfirmView(GenericAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = PasswordResetConfirmSerializer
    throttle_scope = "password_reset"

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = verifications.verify(
            serializer.validated_data["ticket"],
            serializer.validated_data["otp"],
            purpose=PASSWORD_RESET_PURPOSE,
        )
        user = User.objects.filter(
            id=payload["user_id"], is_active=True
        ).first()
        if user is None:
            # ghost ticket, or the account was deactivated mid-flow
            raise ValidationError(code=status_codes.INVALID, detail={"ticket": "This verification ticket is invalid."})

        with transaction.atomic():
            user.set_password(serializer.validated_data["new_password"])
            user.save(update_fields=["password", "updated_at"])
            # invalidate every existing refresh token (F1.3)
            for token in OutstandingToken.objects.filter(user=user):
                BlacklistedToken.objects.get_or_create(token=token)
        return Response({"detail": "Password has been reset. Please log in again."})


class PasswordChangeView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PasswordChangeSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user

        with transaction.atomic():
            user.set_password(serializer.validated_data["new_password"])
            user.save(update_fields=["password", "updated_at"])
            # kill every existing session (F1.4)
            for token in OutstandingToken.objects.filter(user=user):
                BlacklistedToken.objects.get_or_create(token=token)

        # re-issue a fresh pair so this device stays logged in
        refresh = RefreshToken.for_user(user)
        response = Response({"access": str(refresh.access_token), "refresh": str(refresh)})
        _set_refresh_token_cookie(response, refresh)
        return response


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


class UserProfileViewSet(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Current authenticated user's profile.

    ``GET /profile`` — user fields plus ``allowed_permissions`` and
    ``allowed_sites``.
    ``PATCH /profile`` — update name, email, phone.
    Password changes use ``/auth/password/change`` or reset.
    Company config and the site catalog are on ``GET /company``.
    No Django model-permission gate (any authenticated user).
    """

    serializer_class = ProfileDetailSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "head", "options"]

    def get_serializer_class(self):
        if self.action in ("partial_update", "update"):
            return ProfileUpdateSerializer
        return ProfileDetailSerializer

    def get_object(self):
        return (
            User.objects.filter(pk=self.request.user.pk)
            .prefetch_related(
                "groups",
                "groups__permissions",
                "user_permissions",
            )
            .get()
        )

    def retrieve(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object())
        return Response(serializer.data)

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        from activity.services import log_updated, snapshot_user

        instance = self.get_object()
        old_snapshot = snapshot_user(instance)
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        log_updated(request.user, serializer.instance, old_snapshot=old_snapshot)
        return Response(
            ProfileDetailSerializer(
                self.get_object(),
                context=self.get_serializer_context(),
            ).data
        )


class UserViewSet(viewsets.ModelViewSet):
    """Company-scoped user management.

    POST accepts an initial ``password`` so the admin can share credentials,
    plus optional ``groups`` and ``allowed_sites``. PATCH cannot change
    passwords (only ``is_active``, ``groups``, ``allowed_sites``).
    DELETE requires the admin's own ``password`` and hard-deletes the user
    (``UserSite`` cascades; activity actor FKs null).
    """

    serializer_class = UserDetailSerializer
    queryset = User.objects.none()
    pagination_class = StandardPagination
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["is_active", "is_companyadmin"]
    search_fields = ["name", "phone_number"]

    def get_serializer_class(self):
        if self.action == "list":
            return UserListSerializer
        if self.action == "create":
            return UserCreateSerializer
        if self.action == "partial_update":
            return UserUpdateSerializer
        if self.action == "destroy":
            return UserDeleteSerializer
        return UserDetailSerializer

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated or user.company_id is None:
            return User.objects.none()

        return (
            User.objects.filter(
                company_id=user.company_id,
            ).exclude(id=user.id)
            .prefetch_related(
                "groups",
                "groups__permissions",
                "user_permissions",
                "sites__site",
            )
            .order_by("name")
        )

    @transaction.atomic
    def perform_create(self, serializer):
        company = self.request.user.company
        try:
            SubscriptionService.validate_active_user_limit(company)
        except SubscriptionLimitExceededError as exc:
            raise SubscriptionLimitExceeded(detail=str(exc))
        except SubscriptionExpiredError:
            raise SubscriptionExpired()
        serializer.save(
            company=company,
            is_active=True,
            is_staff=False,
            is_superuser=False,
            is_companyadmin=False,
        )
        from activity.services import log_created

        # activity log for user create
        log_created(self.request.user, serializer.instance)

    @transaction.atomic
    def perform_update(self, serializer):
        from activity.services import log_updated, snapshot_user

        instance = serializer.instance
        becoming_active = (
            not instance.is_active
            and serializer.validated_data.get("is_active", False) is True
        )
        if becoming_active:
            try:
                SubscriptionService.validate_active_user_limit(instance.company)
            except SubscriptionLimitExceededError as exc:
                raise SubscriptionLimitExceeded(detail=str(exc))
            except SubscriptionExpiredError:
                raise SubscriptionExpired()
        old_snapshot = snapshot_user(instance)
        serializer.save()
        log_updated(self.request.user, serializer.instance, old_snapshot=old_snapshot)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @transaction.atomic
    def perform_destroy(self, instance):
        from activity.services import log_deleted

        log_deleted(self.request.user, instance)
        instance.delete()
