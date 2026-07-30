from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
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
from core.permissions import DjangoModelPermissionsWithView
from core.services import SubscriptionService
from company.models import Company
from .models import User, UserSite
from .permissions import get_target_user, get_target_site
from .serializers import (
    # registration serializers
    RegisterConfirmSerializer,
    RegisterSerializer,
    ResendOtpSerializer,
    UserCreateSerializer,
    UserProfileSerializer,

    # password reset serializers
    PasswordResetSerializer,
    PasswordResetConfirmSerializer,
    PasswordChangeSerializer,

    # token serializers
    CookieTokenObtainPairSerializer,
    CookieTokenRefreshSerializer,
    CookieTokenBlacklistSerializer,

    # company user management
    SiteUserSerializer,
    UserGroupSerializer,
    UserListSerializer,
    UserSiteSerializer,
    UserUpdateSerializer,
)

REGISTER_PURPOSE = "register"
PASSWORD_RESET_PURPOSE = "password_reset"
COMPANY_ADMIN_GROUP = "Company Admin"

def _set_refresh_token_cookie(response, refresh_token=None):
    if refresh_token is not None:
        response.set_cookie(
            key=getattr(settings, "REFRESH_TOKEN_COOKIE_NAME", "refresh_token"),
            value=str(refresh_token),
            max_age=int(jwt_settings.REFRESH_TOKEN_LIFETIME.total_seconds()),
            httponly=True,
            secure=getattr(settings, "REFRESH_TOKEN_COOKIE_SECURE", not settings.DEBUG),
            samesite=getattr(settings, "REFRESH_TOKEN_COOKIE_SAMESITE", "Lax"),
            path=getattr(settings, "REFRESH_TOKEN_COOKIE_PATH", "/api/v1/auth/token"),
        )

def _clear_refresh_token_cookie(response):
    response.delete_cookie(
        key=getattr(settings, "REFRESH_TOKEN_COOKIE_NAME", "refresh_token"),
        path=getattr(settings, "REFRESH_TOKEN_COOKIE_PATH", "/api/v1/auth/token"),
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
        response = _ticket_response(ticket, status_code=status.HTTP_201_CREATED)
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
        response = _ticket_response(ticket, status_code=status.HTTP_200_OK)        
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
            raise ValidationError(code=status_codes.ALREADY_REGISTERED, detail={"phone_number": "This phone number is already registered."})
        serialized_user = UserProfileSerializer(user)
        return Response(data=serialized_user.data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def _confirm_registration(self, payload):
        company = Company.objects.create(name=payload["company_name"])
        user = User(
            name=payload["name"],
            phone_number=payload["phone_number"],
            email=payload["email"],
            company=company,
            is_active=True,
            is_staff=False,
            is_companyadmin=True,
        )
        user.password = payload["password"]
        user.save()
        admin_group, _ = Group.objects.get_or_create(name=COMPANY_ADMIN_GROUP)
        user.groups.add(admin_group)
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
        name = serializer.validated_data["name"]

        # Anti-enumeration: a ticket is minted and the same 200 body returned
        # whether or not the phone is registered. Only a real, active account
        # gets a deliverable contact — a ghost ticket carries no phone, so
        # nothing is ever sent and its OTP can never be verified.
        # hard rule: the account holder's exact name must match too —
        # keeps reset stricter than a plain phone->OTP flow
        user = User.objects.filter(
            phone_number=phone,
            name=name,
            is_active=True,
            deleted_at__isnull=True,
        ).first()
        ticket, delivery_info = verifications.create_ticket(
            purpose=PASSWORD_RESET_PURPOSE,
            channel=notifications.SMS,
            phone=phone if user else None,
            email=None,
            payload={"user_id": user.id if user else None},
        )

        # ghost tickets (unregistered phone) have no deliverable contact
        if delivery_info["phone"]:
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

        # ghost tickets (unregistered phone) have no deliverable contact
        if delivery_info["phone"]:
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
            id=payload["user_id"], is_active=True, deleted_at__isnull=True
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

    ``GET /profile`` — basic info, groups, permissions, assigned sites.
    ``PATCH /profile`` — update name, email, phone.
    Password changes use ``/auth/password/change`` or reset.
    No Django model-permission gate (any authenticated user).
    """

    serializer_class = UserProfileSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        return (
            User.objects.filter(pk=self.request.user.pk)
            .select_related("company")
            .prefetch_related(
                "groups",
                "groups__permissions",
                "user_permissions",
                "sites__site",
            )
            .get()
        )

    def retrieve(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object())
        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(self.get_serializer(self.get_object()).data)


class UserViewSet(viewsets.ModelViewSet):
    """Company-scoped user management.

    PATCH only updates ``is_active`` and replaces assigned ``groups`` and ``sites``.
    """

    serializer_class = UserProfileSerializer
    queryset = User.objects.none()
    http_method_names = ["get", "post", "patch", "head", "options"]
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
        return UserProfileSerializer

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated or user.company_id is None:
            return User.objects.none()

        return (
            User.objects.filter(
                company_id=user.company_id,
                deleted_at__isnull=True,
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

    @transaction.atomic
    def perform_update(self, serializer):
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
        serializer.save()


class UserGroupViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Nested under ``/users/<user_pk>/groups``.

    List assigned role groups, assign a new one, or remove an assignment.
    Uses Django ``auth.Group`` model permissions (view/add/delete_group).
    """

    serializer_class = UserGroupSerializer
    queryset = Group.objects.none()
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_target_user(self):
        target = get_target_user(self.request, self)
        if target is None:
            raise NotFound()
        return target

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return Group.objects.none()
        return self.get_target_user().groups.all().order_by("name")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group = serializer.validated_data["id"]
        target = self.get_target_user()
        target.groups.add(group)
        return Response(
            UserGroupSerializer(group).data,
            status=status.HTTP_201_CREATED,
        )

    def perform_destroy(self, instance):
        self.get_target_user().groups.remove(instance)


class UserSiteViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Nested under ``/users/<user_pk>/sites``.

    Assign with ``{"site": id}``. Authz: ``accounts.UserSite`` model perms only.
    """

    serializer_class = UserSiteSerializer
    queryset = UserSite.objects.none()
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_target_user(self):
        target = get_target_user(self.request, self)
        if target is None:
            raise NotFound()
        return target

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return UserSite.objects.none()
        return (
            UserSite.objects.filter(
                company_id=self.request.user.company_id,
                user=self.get_target_user(),
            )
            .select_related("user", "site", "created_by")
            .order_by("id")
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        site = serializer.validated_data["site"]
        user = self.get_target_user()
        obj, _created = UserSite.objects.get_or_create(
            user=user,
            site=site,
            defaults={
                "company": request.user.company,
                "created_by": request.user,
            },
        )
        return Response(
            self.get_serializer(obj).data,
            status=status.HTTP_201_CREATED,
        )


class SiteUserViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Nested under ``/sites/<site_pk>/users``.

    Assign with ``{"user": id}``. Authz: ``accounts.UserSite`` model perms only.
    """

    serializer_class = SiteUserSerializer
    queryset = UserSite.objects.none()
    permission_classes = [IsAuthenticated, DjangoModelPermissionsWithView]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_target_site(self):
        site = get_target_site(self.request, self)
        if site is None:
            raise NotFound()
        return site

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return UserSite.objects.none()
        return (
            UserSite.objects.filter(
                company_id=self.request.user.company_id,
                site=self.get_target_site(),
            )
            .select_related("user", "site", "created_by")
            .order_by("id")
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        site = self.get_target_site()
        obj, _created = UserSite.objects.get_or_create(
            user=user,
            site=site,
            defaults={
                "company": request.user.company,
                "created_by": request.user,
            },
        )
        return Response(
            self.get_serializer(obj).data,
            status=status.HTTP_201_CREATED,
        )
