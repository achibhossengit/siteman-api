from unittest.mock import patch
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle
from core import status_codes, verifications
from company.models import Company
from subscription.models import Subscription
from sites.models import Site
from .models import UserSite
from .views import PASSWORD_RESET_PURPOSE, REGISTER_PURPOSE

User = get_user_model()


def _list_results(response):
    """Return list rows from a paginated or unpaginated list response."""
    data = response.data
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    return data


TEST_CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
}
TEST_THROTTLE_RATES = {
    "register": "1000/min",
    "login": "1000/min",
    "password_reset": "1000/min",
    "user": "1000/min",
}


@override_settings(CACHES=TEST_CACHES, REGISTRATION_ENABLED=True)
class RegistrationFlowTests(APITestCase):
    def setUp(self):
        cache.clear()
        # THROTTLE_RATES is a class attribute snapshotted at import time,
        # so override_settings(REST_FRAMEWORK=...) has no effect on it.
        # patch the base class: ScopedRateThrottle and UserRateThrottle
        # both inherit THROTTLE_RATES from SimpleRateThrottle. 
        # So, apply changes in the parent then all children will found it
        throttle_patcher = patch.object(
            SimpleRateThrottle, "THROTTLE_RATES", TEST_THROTTLE_RATES
        )
        throttle_patcher.start()
        self.addCleanup(throttle_patcher.stop)
        self.register_url = reverse("register", kwargs={"version": "v1"})
        self.resend_url = reverse("register-resend-otp", kwargs={"version": "v1"})
        self.confirm_url = reverse("register-confirm", kwargs={"version": "v1"})
        self.valid_payload = {
            "name": "Achib Hossen",
            "phone_number": "+8801712345678",
            "email": "achib@example.com",
            "company_name": "Achib Builders",
            "password": "strong-pass-123",
        }

    def register(self, payload=None):
        """POST /register with delivery mocked. Returns (response, ticket, otp)."""
        with patch("core.notifications.deliver_otp") as mocked:
            response = self.client.post(self.register_url, payload or self.valid_payload)
        ticket = response.data.get("ticket") if response.status_code == 201 else None
        otp = mocked.call_args.kwargs.get("otp") if mocked.call_args else None
        return response, ticket, otp

    # --- register ---

    def test_register_success(self):
        with patch("core.notifications.deliver_otp") as mocked:
            response = self.client.post(self.register_url, self.valid_payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertCountEqual(response.data.keys(), ["ticket", "otp_expires_in", "resend_cooldown"])
        mocked.assert_called_once()
        self.assertEqual(mocked.call_args.kwargs["email"], "achib@example.com")

    def test_register_requires_email(self):
        payload = {**self.valid_payload}
        payload.pop("email")
        response, _, _ = self.register(payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_creates_no_user_until_confirm(self):
        self.register()
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Company.objects.count(), 0)

    def test_register_rejects_registered_phone(self):
        User.objects.create_user(
            phone_number="+8801712345678", name="Existing User", password="strong-pass-123"
        )
        response, _, _ = self.register()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_rejects_weak_password(self):
        weak_passwords = [
            "123",            # too short
            # "12345678",       # numeric only
            # "password",       # too common
            # "achib hossen",   # too similar to the user's name
            "",               # empty
        ]
        for password in weak_passwords:
            with self.subTest(password=password):
                payload = {**self.valid_payload, "password": password}
                response, _, _ = self.register(payload)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_rejects_invalid_phone(self):
        invalid_numbers = [
            "123456565656",      # no country code, not BD format
            "+8802123456789",    # BD but not a mobile prefix
            "+880171234567",     # too short
            "+88017123456789",   # too long
            "abcdefghijk",       # not digits
            "",                  # empty
        ]
        for number in invalid_numbers:
            with self.subTest(phone=number):
                payload = {**self.valid_payload, "phone_number": number}
                response, _, _ = self.register(payload)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # --- resend OTP ---

    def test_resend_within_cooldown_throttled(self):
        _, ticket, _ = self.register()
        with patch("core.notifications.deliver_otp"):
            response = self.client.post(self.resend_url, {"ticket": ticket})
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        
    def test_resend_success(self):
        _, ticket, _ = self.register()
        # disable the cooldown so the resend is allowed immediately
        with patch.object(verifications, "RESEND_COOLDOWN", 0):
            with patch("core.notifications.deliver_otp") as mocked:
                response = self.client.post(self.resend_url, {"ticket": ticket})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["ticket"], ticket)
        # the freshly generated OTP must work on confirm
        new_otp = mocked.call_args.kwargs["otp"]
        confirm = self.client.post(self.confirm_url, {"ticket": ticket, "otp": new_otp})
        self.assertEqual(confirm.status_code, status.HTTP_201_CREATED)
        

    # --- confirm ---

    def test_confirm_creates_company_admin(self):
        _, ticket, otp = self.register()
        response = self.client.post(self.confirm_url, {"ticket": ticket, "otp": otp})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user = User.objects.get(phone_number="+8801712345678")
        self.assertTrue(user.check_password("strong-pass-123"))
        self.assertEqual(user.email, "achib@example.com")
        self.assertEqual(user.company.name, "Achib Builders")
        self.assertTrue(user.is_companyadmin)
        self.assertTrue(user.groups.filter(name="Company Admin").exists())

    def test_confirm_rejects_wrong_otp(self):
        _, ticket, otp = self.register()
        wrong = "000000" if otp != "000000" else "999999"
        response = self.client.post(self.confirm_url, {"ticket": ticket, "otp": wrong})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(User.objects.count(), 0)

    def test_confirm_ticket_is_single_use(self):
        _, ticket, otp = self.register()
        first = self.client.post(self.confirm_url, {"ticket": ticket, "otp": otp})
        second = self.client.post(self.confirm_url, {"ticket": ticket, "otp": otp})
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(CACHES=TEST_CACHES, REGISTRATION_ENABLED=False)
class RegistrationDisabledTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.register_url = reverse("register", kwargs={"version": "v1"})
        self.resend_url = reverse("register-resend-otp", kwargs={"version": "v1"})
        self.confirm_url = reverse("register-confirm", kwargs={"version": "v1"})

    def test_register_blocked(self):
        response = self.client.post(
            self.register_url,
            {
                "name": "Achib Hossen",
                "phone_number": "+8801712345678",
                "company_name": "Achib Builders",
                "password": "strong-pass-123",
                "email": "achib@example.com",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.REGISTRATION_DISABLED,
        )

    def test_resend_blocked(self):
        response = self.client.post(self.resend_url, {"ticket": "unused"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.REGISTRATION_DISABLED,
        )

    def test_confirm_blocked(self):
        response = self.client.post(
            self.confirm_url, {"ticket": "unused", "otp": "123456"}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.REGISTRATION_DISABLED,
        )


@override_settings(CACHES=TEST_CACHES)
class TokenFlowTests(APITestCase):
    """JWT obtain / refresh / blacklist flow, including the httponly
    refresh-token cookie behaviour."""

    REFRESH_TOKEN_COOKIE_NAME = getattr(settings, "REFRESH_TOKEN_COOKIE_NAME", "refresh_token")

    def setUp(self):
        cache.clear()
        self.obtain_url = reverse("token-obtain", kwargs={"version": "v1"})
        self.refresh_url = reverse("token-refresh", kwargs={"version": "v1"})
        self.blacklist_url = reverse("token-blacklist", kwargs={"version": "v1"})
        # patch the base class: ScopedRateThrottle and UserRateThrottle
        # both inherit THROTTLE_RATES from SimpleRateThrottle
        # So, apply changes in the parent then all children will found it
        throttle_patcher = patch.object(
            SimpleRateThrottle, "THROTTLE_RATES", TEST_THROTTLE_RATES
        )
        throttle_patcher.start()
        self.addCleanup(throttle_patcher.stop)
        # jwt_user_authentication_rule requires an active company on the user
        self.company = Company.objects.create(name="Achib Builders")
        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
        )
        self.credentials = {"phone_number": "+8801712345678", "password": "strong-pass-123"}

    def obtain(self):
        """Login and return the response (also stores the cookie on self.client)."""
        return self.client.post(self.obtain_url, self.credentials)

    # --- obtain ---

    def test_obtain_success_sets_refresh_cookie(self):
        response = self.obtain()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(response.data.keys(), ["access", "refresh"])

        cookie = response.cookies[self.REFRESH_TOKEN_COOKIE_NAME]
        self.assertEqual(cookie.value, response.data["refresh"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["path"], "/api/v1/auth/token")

    def test_obtain_rejects_wrong_password(self):
        response = self.client.post(
            self.obtain_url, {"phone_number": "+8801712345678", "password": "wrong-pass"}
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # --- refresh ---

    def test_refresh_with_body_token(self):
        refresh = self.obtain().data["refresh"]
        response = self.client.post(self.refresh_url, {"refresh": refresh})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # ROTATE_REFRESH_TOKENS=True: a new refresh token is issued and set as cookie
        self.assertCountEqual(response.data.keys(), ["access", "refresh"])
        self.assertNotEqual(response.data["refresh"], refresh)
        self.assertEqual(response.cookies[self.REFRESH_TOKEN_COOKIE_NAME].value, response.data["refresh"])

    def test_refresh_falls_back_to_cookie(self):
        self.obtain()  # stores the refresh cookie on self.client
        response = self.client.post(self.refresh_url, {})  # no body token
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(response.data.keys(), ["access", "refresh"])

    def test_refresh_without_any_token(self):
        response = self.client.post(self.refresh_url, {})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_rotated_refresh_token_is_blacklisted(self):
        old_refresh = self.obtain().data["refresh"]
        self.client.post(self.refresh_url, {"refresh": old_refresh})  # rotates
        # BLACKLIST_AFTER_ROTATION=True: the old token must now be rejected
        response = self.client.post(self.refresh_url, {"refresh": old_refresh})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # --- blacklist (logout) ---

    def test_blacklist_invalidates_token_and_clears_cookie(self):
        refresh = self.obtain().data["refresh"]
        response = self.client.post(self.blacklist_url, {"refresh": refresh})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # cookie cleared (deleted cookies are set to empty with max-age=0)
        self.assertEqual(response.cookies[self.REFRESH_TOKEN_COOKIE_NAME].value, "")
        # blacklisted token can no longer be used to refresh
        retry = self.client.post(self.refresh_url, {"refresh": refresh})
        self.assertEqual(retry.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_blacklist_with_invalid_token_still_clears_cookie(self):
        response = self.client.post(self.blacklist_url, {"refresh": "not-a-token"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.cookies[self.REFRESH_TOKEN_COOKIE_NAME].value, "")


@override_settings(CACHES=TEST_CACHES, REGISTRATION_ENABLED=True)
class AuthenticationRateLimitTests(APITestCase):
    """Throttling for the auth endpoints.

    The 'register' scope is shared by register/resend-otp/confirm,
    so those three endpoints share one bucket per client IP.
    The 'login' scope covers token/obtain only.
    The 'password_reset' scope is shared by reset/resend-otp/confirm.
    """

    def setUp(self):
        cache.clear()
        self.register_url = reverse("register", kwargs={"version": "v1"})
        self.resend_url = reverse("register-resend-otp", kwargs={"version": "v1"})
        self.confirm_url = reverse("register-confirm", kwargs={"version": "v1"})
        self.token_obtain_url = reverse("token-obtain", kwargs={"version": "v1"})
        self.reset_url = reverse("password-reset", kwargs={"version": "v1"})
        self.reset_resend_url = reverse("password-reset-resend-otp", kwargs={"version": "v1"})
        self.reset_confirm_url = reverse("password-reset-confirm", kwargs={"version": "v1"})
        # patch the base class: ScopedRateThrottle and UserRateThrottle
        # both inherit THROTTLE_RATES from SimpleRateThrottle
        # So, apply changes in the parent then all children will found it
        throttle_patcher = patch.object(
            SimpleRateThrottle,
            "THROTTLE_RATES",
            {"register": "3/min", "login": "3/min", "password_reset": "3/min", "user": "1000/min"},
        )
        throttle_patcher.start()
        self.addCleanup(throttle_patcher.stop)
        self.register_payload = {
            "name": "Achib Hossen",
            "phone_number": "+8801712345678",
            "email": "achib@example.com",
            "company_name": "Achib Builders",
            "password": "strong-pass-123",
        }
        self.reset_payload = {"phone_number": "+8801712345678"}

    def exhaust_register_scope(self):
        """Use up the whole 'register' bucket (3/min)."""
        with patch("core.notifications.deliver_otp"):
            for _ in range(3):
                response = self.client.post(self.register_url, self.register_payload)
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def exhaust_password_reset_scope(self):
        """Use up the whole 'password_reset' bucket (3/min)."""
        with patch("core.notifications.deliver_otp"):
            for _ in range(3):
                response = self.client.post(self.reset_url, self.reset_payload)
                self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_register_rate_limited(self):
        self.exhaust_register_scope()
        with patch("core.notifications.deliver_otp"):
            blocked = self.client.post(self.register_url, self.register_payload)
        self.assertEqual(blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertIn("Retry-After", blocked.headers)

    def test_resend_and_confirm_share_register_scope(self):
        self.exhaust_register_scope()
        resend = self.client.post(self.resend_url, {"ticket": "any"})
        confirm = self.client.post(self.confirm_url, {"ticket": "any", "otp": "123456"})
        self.assertEqual(resend.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(confirm.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_login_rate_limited(self):
        credentials = {"phone_number": "+8801712345678", "password": "wrong-pass"}
        for _ in range(3):
            response = self.client.post(self.token_obtain_url, credentials)
            self.assertNotEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        blocked = self.client.post(self.token_obtain_url, credentials)
        self.assertEqual(blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertIn("Retry-After", blocked.headers)

    def test_register_and_login_scopes_are_independent(self):
        self.exhaust_register_scope()
        # register bucket is full, but login must still be allowed
        credentials = {"phone_number": "+8801712345678", "password": "wrong-pass"}
        response = self.client.post(self.token_obtain_url, credentials)
        self.assertNotEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_password_reset_rate_limited(self):
        self.exhaust_password_reset_scope()
        with patch("core.notifications.deliver_otp"):
            blocked = self.client.post(self.reset_url, self.reset_payload)
        self.assertEqual(blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertIn("Retry-After", blocked.headers)

    def test_reset_resend_and_confirm_share_password_reset_scope(self):
        self.exhaust_password_reset_scope()
        resend = self.client.post(self.reset_resend_url, {"ticket": "any"})
        confirm = self.client.post(
            self.reset_confirm_url,
            {"ticket": "any", "otp": "123456", "new_password": "new-pass-456"},
        )
        self.assertEqual(resend.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(confirm.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_password_reset_scope_is_independent(self):
        self.exhaust_password_reset_scope()
        # reset bucket is full, but register and login must still be allowed
        with patch("core.notifications.deliver_otp"):
            register = self.client.post(self.register_url, self.register_payload)
        credentials = {"phone_number": "+8801712345678", "password": "wrong-pass"}
        login = self.client.post(self.token_obtain_url, credentials)
        self.assertNotEqual(register.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertNotEqual(login.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_user_throttle_backstops_authenticated_endpoints(self):
        change_url = reverse("password-change", kwargs={"version": "v1"})
        company = Company.objects.create(name="Achib Builders")
        User.objects.create_user(
            phone_number="+8801912345678",
            name="Rate User",
            password="strong-pass-123",
            company=company,
        )
        credentials = {"phone_number": "+8801912345678", "password": "strong-pass-123"}
        access = self.client.post(self.token_obtain_url, credentials).data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        # UserRateThrottle has no own THROTTLE_RATES attr, so this shadows the
        # SimpleRateThrottle patch for the 'user' scope only
        # So, apply changes in the parent then all children will found it
        with patch.object(UserRateThrottle, "THROTTLE_RATES", {"user": "3/min"}):
            body = {"current_password": "wrong-pass", "new_password": "new-pass-456"}
            for _ in range(3):
                response = self.client.post(change_url, body)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            blocked = self.client.post(change_url, body)
        self.assertEqual(blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertIn("Retry-After", blocked.headers)


@override_settings(CACHES=TEST_CACHES)
class PasswordResetFlowTests(APITestCase):
    """password/reset -> resend-otp -> confirm, including the
    anti-enumeration behaviour (ghost tickets for unknown phones)."""

    def setUp(self):
        cache.clear()
        # patch the base class: ScopedRateThrottle and UserRateThrottle
        # both inherit THROTTLE_RATES from SimpleRateThrottle
        # So, apply changes in the parent then all children will found it
        throttle_patcher = patch.object(
            SimpleRateThrottle, "THROTTLE_RATES", TEST_THROTTLE_RATES
        )
        throttle_patcher.start()
        self.addCleanup(throttle_patcher.stop)
        self.reset_url = reverse("password-reset", kwargs={"version": "v1"})
        self.resend_url = reverse("password-reset-resend-otp", kwargs={"version": "v1"})
        self.confirm_url = reverse("password-reset-confirm", kwargs={"version": "v1"})
        self.obtain_url = reverse("token-obtain", kwargs={"version": "v1"})
        self.refresh_url = reverse("token-refresh", kwargs={"version": "v1"})
        self.company = Company.objects.create(name="Achib Builders")
        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            email="achib@example.com",
            password="old-pass-123",
            company=self.company,
        )

    def request_reset(self, phone="+8801712345678"):
        """POST /password/reset with delivery mocked.
        Returns (response, ticket, otp, mocked)."""
        with patch("core.notifications.deliver_otp") as mocked:
            response = self.client.post(
                self.reset_url, {"phone_number": phone}
            )
        ticket = response.data.get("ticket") if response.status_code == 200 else None
        otp = mocked.call_args.kwargs.get("otp") if mocked.call_args else None
        return response, ticket, otp, mocked

    # --- request ---

    def test_reset_request_sends_otp_to_stored_email(self):
        response, ticket, _, mocked = self.request_reset()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(response.data.keys(), ["ticket", "otp_expires_in", "resend_cooldown"])
        self.assertIsNotNone(ticket)
        mocked.assert_called_once()
        self.assertEqual(mocked.call_args.kwargs["email"], "achib@example.com")

    def test_reset_request_invalid_phone_same_response_no_delivery(self):
        response, ticket, _, mocked = self.request_reset(phone="+8801912345678")
        # identical 200 body — the caller can not tell the phone is unregistered
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(response.data.keys(), ["ticket", "otp_expires_in", "resend_cooldown"])
        self.assertIsNotNone(ticket)
        mocked.assert_not_called()

    def test_reset_request_inactive_user_gets_ghost_ticket(self):
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        response, _, _, mocked = self.request_reset()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mocked.assert_not_called()

    def test_reset_request_user_without_email_gets_no_delivery(self):
        self.user.email = None
        self.user.save(update_fields=["email", "updated_at"])
        response, ticket, _, mocked = self.request_reset()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(ticket)
        mocked.assert_not_called()

    def test_reset_request_rejects_invalid_phone(self):
        response, _, _, _ = self.request_reset(phone="+8802123456789")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reset_request_normalizes_phone_before_user_lookup(self):
        _, _, _, mocked = self.request_reset(phone="01712345678")
        self.assertEqual(mocked.call_args.kwargs["email"], "achib@example.com")

    # --- resend OTP ---

    def test_reset_resend_within_cooldown_throttled(self):
        _, ticket, _, _ = self.request_reset()
        with patch("core.notifications.deliver_otp"):
            response = self.client.post(self.resend_url, {"ticket": ticket})
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_reset_resend_success(self):
        _, ticket, _, _ = self.request_reset()
        with patch.object(verifications, "RESEND_COOLDOWN", 0):
            with patch("core.notifications.deliver_otp") as mocked:
                response = self.client.post(self.resend_url, {"ticket": ticket})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # the freshly generated OTP must work on confirm
        new_otp = mocked.call_args.kwargs["otp"]
        confirm = self.client.post(
            self.confirm_url, {"ticket": ticket, "otp": new_otp, "new_password": "new-pass-456"}
        )
        self.assertEqual(confirm.status_code, status.HTTP_200_OK)

    def test_reset_resend_ghost_ticket_no_delivery(self):
        _, ticket, _, _ = self.request_reset(phone="+8801912345678")
        with patch.object(verifications, "RESEND_COOLDOWN", 0):
            with patch("core.notifications.deliver_otp") as mocked:
                response = self.client.post(self.resend_url, {"ticket": ticket})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mocked.assert_not_called()

    def test_reset_resend_rejects_ticket_of_other_purpose(self):
        ticket, _ = verifications.create_ticket(
            purpose=REGISTER_PURPOSE, email="achib@example.com", payload={},
        )
        response = self.client.post(self.resend_url, {"ticket": ticket})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # --- confirm ---

    def test_reset_confirm_sets_new_password(self):
        _, ticket, otp, _ = self.request_reset()
        response = self.client.post(
            self.confirm_url, {"ticket": ticket, "otp": otp, "new_password": "new-pass-456"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("new-pass-456"))
        self.assertFalse(self.user.check_password("old-pass-123"))

    def test_reset_confirm_invalidates_existing_refresh_tokens(self):
        credentials = {"phone_number": "+8801712345678", "password": "old-pass-123"}
        refresh = self.client.post(self.obtain_url, credentials).data["refresh"]

        _, ticket, otp, _ = self.request_reset()
        self.client.post(
            self.confirm_url, {"ticket": ticket, "otp": otp, "new_password": "new-pass-456"}
        )
        # every pre-reset refresh token is blacklisted (F1.3)
        response = self.client.post(self.refresh_url, {"refresh": refresh})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_reset_confirm_rejects_wrong_otp(self):
        _, ticket, otp, _ = self.request_reset()
        wrong = "000000" if otp != "000000" else "999999"
        response = self.client.post(
            self.confirm_url, {"ticket": ticket, "otp": wrong, "new_password": "new-pass-456"}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("old-pass-123"))

    def test_reset_confirm_rejects_weak_password(self):
        _, ticket, otp, _ = self.request_reset()
        response = self.client.post(
            self.confirm_url, {"ticket": ticket, "otp": otp, "new_password": "123"}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reset_confirm_ticket_is_single_use(self):
        _, ticket, otp, _ = self.request_reset()
        body = {"ticket": ticket, "otp": otp, "new_password": "new-pass-456"}
        first = self.client.post(self.confirm_url, body)
        second = self.client.post(self.confirm_url, body)
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reset_confirm_ghost_ticket_rejected_even_with_correct_otp(self):
        # unknown phone => payload carries user_id=None; even a "valid" OTP
        # (impossible for a real caller, forged here) must not pass
        ticket, delivery_info = verifications.create_ticket(
            purpose=PASSWORD_RESET_PURPOSE,
            email=None,
            payload={"user_id": None},
        )
        response = self.client.post(
            self.confirm_url,
            {"ticket": ticket, "otp": delivery_info["otp"], "new_password": "new-pass-456"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reset_confirm_rejects_user_deactivated_mid_flow(self):
        _, ticket, otp, _ = self.request_reset()
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        response = self.client.post(
            self.confirm_url, {"ticket": ticket, "otp": otp, "new_password": "new-pass-456"}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("old-pass-123"))


@override_settings(CACHES=TEST_CACHES)
class PasswordChangeTests(APITestCase):
    """password/change: authenticated, verifies the current password,
    kills every other session and re-issues a pair for this device."""

    REFRESH_TOKEN_COOKIE_NAME = getattr(settings, "REFRESH_TOKEN_COOKIE_NAME", "refresh_token")

    def setUp(self):
        cache.clear()
        # patch the base class: ScopedRateThrottle and UserRateThrottle
        # both inherit THROTTLE_RATES from SimpleRateThrottle
        # So, apply changes in the parent then all children will found it
        throttle_patcher = patch.object(
            SimpleRateThrottle, "THROTTLE_RATES", TEST_THROTTLE_RATES
        )
        throttle_patcher.start()
        self.addCleanup(throttle_patcher.stop)
        self.obtain_url = reverse("token-obtain", kwargs={"version": "v1"})
        self.refresh_url = reverse("token-refresh", kwargs={"version": "v1"})
        self.change_url = reverse("password-change", kwargs={"version": "v1"})
        self.company = Company.objects.create(name="Achib Builders")
        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="old-pass-123",
            company=self.company,
        )
        self.credentials = {"phone_number": "+8801712345678", "password": "old-pass-123"}

    def login(self):
        """Obtain a pair and authenticate the test client with the access token."""
        data = self.client.post(self.obtain_url, self.credentials).data
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {data['access']}")
        return data

    def change(self, current="old-pass-123", new="new-pass-456"):
        return self.client.post(
            self.change_url, {"current_password": current, "new_password": new}
        )

    def test_change_requires_authentication(self):
        response = self.change()
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_change_success_sets_new_password_and_reissues_pair(self):
        self.login()
        response = self.change()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(response.data.keys(), ["access", "refresh"])
        cookie = response.cookies[self.REFRESH_TOKEN_COOKIE_NAME]
        self.assertEqual(cookie.value, response.data["refresh"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("new-pass-456"))
        self.assertFalse(self.user.check_password("old-pass-123"))

    def test_change_rejects_wrong_current_password(self):
        self.login()
        response = self.change(current="wrong-pass")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("old-pass-123"))

    def test_change_rejects_weak_new_password(self):
        self.login()
        response = self.change(new="123")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_change_kills_other_sessions_but_not_this_one(self):
        # device A logs in, then device B logs in and changes the password
        device_a_refresh = self.client.post(self.obtain_url, self.credentials).data["refresh"]
        self.login()
        response = self.change()
        # device A's refresh token is blacklisted
        retry = self.client.post(self.refresh_url, {"refresh": device_a_refresh})
        self.assertEqual(retry.status_code, status.HTTP_401_UNAUTHORIZED)
        # the re-issued pair from the change response still works
        keep = self.client.post(self.refresh_url, {"refresh": response.data["refresh"]})
        self.assertEqual(keep.status_code, status.HTTP_200_OK)

    def test_change_reissued_access_token_is_usable(self):
        self.login()
        new_access = self.change().data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {new_access}")
        response = self.change(current="new-pass-456", new="another-pass-789")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class UserAPITestCase(APITestCase):
    """Shared fixtures for ``/users`` management endpoints."""

    def setUp(self):
        self.company = Company.objects.create(name="Achib Builders")
        self.subscription = Subscription.objects.get(company=self.company)
        self.subscription.active_user_limit = 10
        self.subscription.save(update_fields=["active_user_limit"])

        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
            is_companyadmin=True,
        )
        self._grant_user_permissions(self.user)
        self.client.force_authenticate(user=self.user)
        self.list_url = reverse("user-list", kwargs={"version": "v1"})

    def _grant_user_permissions(self, user, codenames=None):
        codenames = codenames or [
            "view_user",
            "add_user",
            "change_user",
            "delete_user",
        ]
        ct = ContentType.objects.get_for_model(User)
        perms = Permission.objects.filter(content_type=ct, codename__in=codenames)
        user.user_permissions.add(*perms)

    def _detail_url(self, user_id):
        return reverse("user-detail", kwargs={"version": "v1", "pk": user_id})

    def _create_company_user(self, name="Karim", phone="+8801711111111", **kwargs):
        defaults = {
            "phone_number": phone,
            "name": name,
            "password": "strong-pass-123",
            "company": self.company,
            "is_companyadmin": False,
        }
        defaults.update(kwargs)
        return User.objects.create_user(**defaults)


class UserAuthPermissionTests(UserAPITestCase):
    def test_unauthenticated_list_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_add_permission_returns_403(self):
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_user_permissions(self.user, ["view_user"])
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            self.list_url,
            {
                "name": "New User",
                "phone_number": "+8801799999999",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_view_permission_returns_403(self):
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_change_permission_returns_403(self):
        other = self._create_company_user(phone="+8801711100001")
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_user_permissions(self.user, ["view_user", "add_user"])
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(self._detail_url(other.pk), {"name": "Nope"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class UserCRUDTests(UserAPITestCase):
    def test_list_excludes_self(self):
        other = self._create_company_user(phone="+8801711110000")
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(_list_results(response)), 1)
        self.assertEqual(_list_results(response)[0]["id"], other.pk)

    def test_create_user_success(self):
        response = self.client.post(
            self.list_url,
            {
                "name": "Site Manager",
                "phone_number": "01711112222",
                "password": "initial-pass-123",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "Site Manager")
        self.assertEqual(response.data["phone_number"], "01711112222")
        self.assertEqual(response.data["company"], self.company.pk)
        self.assertTrue(response.data["is_active"])
        self.assertFalse(response.data["is_companyadmin"])
        self.assertNotIn("password", response.data)
        self.assertNotIn("email", response.data)

        created = User.objects.get(pk=response.data["id"])
        self.assertTrue(created.check_password("initial-pass-123"))
        self.assertTrue(created.has_usable_password())
        self.assertIn(created.email, (None, ""))
        self.assertFalse(created.is_staff)
        self.assertFalse(created.is_superuser)

    def test_create_requires_password(self):
        response = self.client.post(
            self.list_url,
            {
                "name": "No Pass",
                "phone_number": "+8801711112211",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_rejects_weak_password(self):
        response = self.client.post(
            self.list_url,
            {
                "name": "Weak Pass",
                "phone_number": "+8801711112212",
                "password": "123",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_forces_non_admin_flags(self):
        response = self.client.post(
            self.list_url,
            {
                "name": "Forced",
                "phone_number": "+8801711113333",
                "password": "strong-pass-123",
                "is_companyadmin": True,
                "is_active": False,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.data["is_companyadmin"])
        self.assertTrue(response.data["is_active"])

    def test_list_uses_list_serializer_fields(self):
        other = self._create_company_user()
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(_list_results(response)), 1)
        self.assertCountEqual(
            _list_results(response)[0].keys(),
            [
                "id",
                "name",
                "photo",
                "phone_number",
                "email",
                "is_active",
                "is_companyadmin",
            ],
        )
        ids = {row["id"] for row in _list_results(response)}
        self.assertIn(other.pk, ids)

    def test_retrieve_user_detail(self):
        other = self._create_company_user(name="Detail User", phone="+8801711114444")
        response = self.client.get(self._detail_url(other.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Detail User")
        self.assertIn("company", response.data)
        self.assertNotIn("password", response.data)

    def test_patch_is_active(self):
        other = self._create_company_user(
            name="Old Name",
            phone="+8801711115555",
            email="old@example.com",
        )
        response = self.client.patch(
            self._detail_url(other.pk),
            {"is_active": False},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["is_active"])
        other.refresh_from_db()
        self.assertFalse(other.is_active)
        self.assertTrue(other.check_password("strong-pass-123"))

    def test_patch_groups_replaces_assignments(self):
        other = self._create_company_user(phone="+8801711116666")
        site_manager = Group.objects.get(name="Site Manager")
        site_auditor = Group.objects.get(name="Site Auditor")
        other.groups.add(site_manager)

        response = self.client.patch(
            self._detail_url(other.pk),
            {"groups": ["Site Auditor"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["groups"],
            [{"id": site_auditor.pk, "name": "Site Auditor"}],
        )
        self.assertCountEqual(
            other.groups.values_list("id", flat=True),
            [site_auditor.pk],
        )

    def test_patch_groups_rejects_multiple_groups(self):
        other = self._create_company_user(phone="+8801711116667")
        response = self.client.patch(
            self._detail_url(other.pk),
            {"groups": ["Site Manager", "Site Auditor"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.INVALID,
        )
        self.assertFalse(other.groups.exists())

    def test_patch_groups_rejects_company_admin(self):
        other = self._create_company_user(phone="+8801711116668")
        response = self.client.patch(
            self._detail_url(other.pk),
            {"groups": ["Company Admin"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(other.groups.exists())

    def test_patch_groups_rejects_unknown_group_name(self):
        other = self._create_company_user(phone="+8801711116766")
        Group.objects.create(name="Unassignable Group")

        response = self.client.patch(
            self._detail_url(other.pk),
            {"groups": ["Unassignable Group"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(other.groups.exists())

    def test_patch_sites_replaces_assignments(self):
        other = self._create_company_user(phone="+8801711116767")
        old_site = Site.objects.create(
            name="Old Site",
            company=self.company,
        )
        site_a = Site.objects.create(
            name="Site A",
            company=self.company,
        )
        site_b = Site.objects.create(
            name="Site B",
            company=self.company,
        )
        UserSite.objects.create(
            user=other,
            site=old_site,
            company=self.company,
        )

        response = self.client.patch(
            self._detail_url(other.pk),
            {"sites": [site_a.pk, site_b.pk]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(response.data["sites"], [site_a.pk, site_b.pk])
        self.assertCountEqual(
            other.sites.values_list("site_id", flat=True),
            [site_a.pk, site_b.pk],
        )

    def test_patch_sites_rejects_site_from_other_company(self):
        other = self._create_company_user(phone="+8801711116868")
        other_company = Company.objects.create(name="Other Company")
        foreign_site = Site.objects.create(
            name="Foreign Site",
            company=other_company,
        )

        response = self.client.patch(
            self._detail_url(other.pk),
            {"sites": [foreign_site.pk]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(other.sites.exists())

    def test_patch_empty_sites_clears_assignments(self):
        other = self._create_company_user(phone="+8801711116969")
        site = Site.objects.create(
            name="Assigned Site",
            company=self.company,
        )
        UserSite.objects.create(
            user=other,
            site=site,
            company=self.company,
        )

        response = self.client.patch(
            self._detail_url(other.pk),
            {"sites": []},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["sites"], [])
        self.assertFalse(other.sites.exists())

    def test_patch_ignores_fields_other_than_groups_sites_and_is_active(self):
        other = self._create_company_user(
            name="Original Name",
            phone="+8801711117777",
            email="original@example.com",
        )
        response = self.client.patch(
            self._detail_url(other.pk),
            {
                "phone_number": "+8801799999999",
                "password": "hijacked-pass-999",
                "name": "Changed Name",
                "email": "changed@example.com",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        other.refresh_from_db()
        self.assertEqual(other.name, "Original Name")
        self.assertEqual(other.phone_number, "+8801711117777")
        self.assertEqual(other.email, "original@example.com")
        self.assertTrue(other.check_password("strong-pass-123"))

    def test_patch_same_name_allowed(self):
        other = self._create_company_user(name="Keep", phone="+8801711117777")
        response = self.client.patch(
            self._detail_url(other.pk),
            {"is_active": False},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_put_not_allowed(self):
        other = self._create_company_user(phone="+8801711118888")
        response = self.client.put(
            self._detail_url(other.pk),
            {
                "name": "Nope",
                "phone_number": "+8801711118888",
                "password": "strong-pass-123",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_delete_removes_user_and_writes_activity(self):
        from activity.models import ActivityAction, ActivityEntityType, ActivityLog

        other = self._create_company_user(phone="+8801711119999", name="To Delete")
        response = self.client.delete(self._detail_url(other.pk))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(User.objects.filter(pk=other.pk).exists())
        log = ActivityLog.objects.filter(
            entity_type=ActivityEntityType.USER,
            entity_id=other.pk,
            action=ActivityAction.DELETED,
        ).latest("id")
        self.assertEqual(log.actor_id, self.user.pk)
        self.assertEqual(log.changes["name"], "To Delete")

    def test_cannot_delete_self(self):
        response = self.client.delete(self._detail_url(self.user.pk))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_missing_delete_permission_returns_403(self):
        other = self._create_company_user(phone="+8801711100099")
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_user_permissions(self.user, ["view_user", "change_user"])
        self.client.force_authenticate(user=self.user)
        response = self.client.delete(self._detail_url(other.pk))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(User.objects.filter(pk=other.pk).exists())


class UserValidationTests(UserAPITestCase):
    def test_create_ignores_client_email(self):
        response = self.client.post(
            self.list_url,
            {
                "name": "No Email",
                "phone_number": "+8801711118787",
                "email": "ignored@example.com",
                "password": "strong-pass-123",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn("email", response.data)
        created = User.objects.get(pk=response.data["id"])
        self.assertIn(created.email, (None, ""))

    def test_duplicate_phone_rejected(self):
        self._create_company_user(phone="+8801711118888")
        response = self.client.post(
            self.list_url,
            {
                "name": "Another",
                "phone_number": "+8801711118888",
                "password": "strong-pass-123",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.ALREADY_REGISTERED,
        )

    def test_duplicate_name_in_company_rejected(self):
        self._create_company_user(name="Karim", phone="+8801711119999")
        response = self.client.post(
            self.list_url,
            {
                "name": "Karim",
                "phone_number": "+8801711120000",
                "password": "strong-pass-123",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.USER_NAME_EXISTS,
        )


class UserFilterIsolationTests(UserAPITestCase):
    def test_cannot_see_other_company_users(self):
        other = Company.objects.create(name="Other Co")
        User.objects.create_user(
            phone_number="+8801811111111",
            name="Foreign",
            password="strong-pass-123",
            company=other,
        )
        colleague = self._create_company_user(phone="+8801711110000")
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(_list_results(response)), 1)
        self.assertEqual(_list_results(response)[0]["id"], colleague.pk)

    def test_filter_by_is_active(self):
        active = self._create_company_user(name="Active", phone="+8801711122222")
        inactive = self._create_company_user(
            name="Inactive", phone="+8801711123333", is_active=False
        )
        response = self.client.get(self.list_url, {"is_active": "true"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in _list_results(response)}
        self.assertNotIn(self.user.pk, ids)
        self.assertIn(active.pk, ids)
        self.assertNotIn(inactive.pk, ids)

    def test_search_by_name(self):
        self._create_company_user(name="Karim Mia", phone="+8801711124444")
        self._create_company_user(name="Rahim Uddin", phone="+8801711125555")
        response = self.client.get(self.list_url, {"search": "Karim"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(_list_results(response)), 1)
        self.assertEqual(_list_results(response)[0]["name"], "Karim Mia")


class UserSubscriptionTests(UserAPITestCase):
    def test_create_blocked_when_active_user_limit_exceeded(self):
        self.subscription.active_user_limit = 1
        self.subscription.save(update_fields=["active_user_limit"])
        # self.user already counts as the one active slot
        response = self.client.post(
            self.list_url,
            {
                "name": "Overflow",
                "phone_number": "+8801711126666",
                "password": "strong-pass-123",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SUBSCRIPTION_LIMIT_EXCEEDED,
        )
        self.assertFalse(User.objects.filter(name="Overflow").exists())

    def test_reactivate_blocked_when_active_user_limit_exceeded(self):
        inactive = self._create_company_user(
            name="Inactive Slot",
            phone="+8801711127777",
            is_active=False,
        )
        self.subscription.active_user_limit = 1
        self.subscription.save(update_fields=["active_user_limit"])

        response = self.client.patch(
            self._detail_url(inactive.pk),
            {"is_active": True},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["errors"][0]["code"],
            status_codes.SUBSCRIPTION_LIMIT_EXCEEDED,
        )
        inactive.refresh_from_db()
        self.assertFalse(inactive.is_active)


class UserProfileAPITestCase(APITestCase):
    """Shared fixtures for ``GET /profile``."""

    def setUp(self):
        self.company = Company.objects.create(name="Achib Builders")
        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
            email="achib@example.com",
            is_companyadmin=True,
        )
        self.site_manager = Group.objects.get(name="Site Manager")
        self.user.groups.add(self.site_manager)
        ct = ContentType.objects.get_for_model(User)
        self.view_user_perm = Permission.objects.get(
            content_type=ct, codename="view_user"
        )
        self.user.user_permissions.add(self.view_user_perm)

        self.site = Site.objects.create(
            name="Padma Bridge",
            company=self.company,
        )
        UserSite.objects.create(
            user=self.user,
            site=self.site,
            company=self.company,
        )
        self.client.force_authenticate(user=self.user)
        self.url = reverse("user-profile", kwargs={"version": "v1"})


class UserProfileAuthTests(UserProfileAPITestCase):
    def test_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_post_not_allowed(self):
        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_put_not_allowed(self):
        response = self.client.put(self.url, {"name": "Nope"})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_delete_not_allowed(self):
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class UserProfileRetrieveTests(UserProfileAPITestCase):
    def test_get_returns_basic_info(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.user.pk)
        self.assertEqual(response.data["name"], "Achib Hossen")
        self.assertEqual(response.data["phone_number"], "01712345678")
        self.assertEqual(response.data["email"], "achib@example.com")
        self.assertIsNone(response.data["photo"])
        self.assertTrue(response.data["is_companyadmin"])
        self.assertEqual(
            response.data["company"],
            {"id": self.company.pk, "name": "Achib Builders"},
        )

    def test_get_returns_allowed_groups(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(
            {"id": self.site_manager.pk, "name": "Site Manager"},
            response.data["allowed_groups"],
        )
        self.assertNotIn("groups", response.data)

    def test_get_returns_allowed_permissions(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("accounts.view_user", response.data["allowed_permissions"])
        self.assertNotIn("permissions", response.data)

    def test_get_returns_assigned_sites_as_allowed_sites(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["allowed_sites"], [self.site.pk])

    def test_companyadmin_allowed_sites_are_all_company_site_ids(self):
        other_site = Site.objects.create(
            name="Jamuna Bridge",
            company=self.company,
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(
            response.data["allowed_sites"],
            [self.site.pk, other_site.pk],
        )

    def test_sites_is_company_catalog_with_fields(self):
        other_site = Site.objects.create(
            name="Jamuna Bridge",
            company=self.company,
        )
        foreign_company = Company.objects.create(name="Other Co")
        Site.objects.create(name="Foreign Site", company=foreign_company)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = {row["id"]: row for row in response.data["sites"]}
        self.assertCountEqual(rows, [self.site.pk, other_site.pk])
        self.assertEqual(
            rows[self.site.pk],
            {
                "id": self.site.pk,
                "name": "Padma Bridge",
                "is_active": True,
                "is_closed": False,
            },
        )
        self.assertEqual(rows[other_site.pk]["name"], "Jamuna Bridge")

    def test_non_admin_allowed_sites_are_only_assigned(self):
        unassigned = Site.objects.create(
            name="Unassigned Site",
            company=self.company,
        )
        worker = User.objects.create_user(
            phone_number="+8801799999999",
            name="Worker",
            password="strong-pass-123",
            company=self.company,
            is_companyadmin=False,
        )
        UserSite.objects.create(
            user=worker,
            site=self.site,
            company=self.company,
        )
        self.client.force_authenticate(user=worker)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["allowed_sites"], [self.site.pk])
        self.assertCountEqual(
            [row["id"] for row in response.data["sites"]],
            [self.site.pk, unassigned.pk],
        )

    def test_get_is_only_request_user(self):
        other = User.objects.create_user(
            phone_number="+8801711111111",
            name="Karim",
            password="strong-pass-123",
            company=self.company,
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.user.pk)
        self.assertNotEqual(response.data["id"], other.pk)


class UserProfileUpdateTests(UserProfileAPITestCase):
    def test_patch_basic_info(self):
        response = self.client.patch(
            self.url,
            {
                "name": "New Achib",
                "email": "new@example.com",
                "phone_number": "+8801712345600",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "New Achib")
        self.assertEqual(response.data["email"], "new@example.com")
        self.assertEqual(response.data["phone_number"], "01712345600")
        self.user.refresh_from_db()
        self.assertEqual(self.user.name, "New Achib")
        self.assertEqual(self.user.email, "new@example.com")
        self.assertEqual(self.user.phone_number, "+8801712345600")

    def test_patch_ignores_flags(self):
        response = self.client.patch(
            self.url,
            {
                "is_companyadmin": False,
                "is_active": False,
                "is_staff": True,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_companyadmin)
        self.assertTrue(self.user.is_active)
        self.assertFalse(self.user.is_staff)

    def test_patch_ignores_password(self):
        response = self.client.patch(
            self.url,
            {
                "password": "newer-pass-456",
                "current_password": "strong-pass-123",
                "name": "Still Achib",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Still Achib")
        self.assertNotIn("access", response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("strong-pass-123"))
        self.assertEqual(self.user.name, "Still Achib")

    def test_patch_photo(self):
        import tempfile
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (1, 1), "red").save(buf, format="PNG")
        upload = SimpleUploadedFile(
            "avatar.png",
            buf.getvalue(),
            content_type="image/png",
        )
        with tempfile.TemporaryDirectory() as media:
            with override_settings(MEDIA_ROOT=media):
                response = self.client.patch(
                    self.url,
                    {"photo": upload},
                    format="multipart",
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertIsNotNone(response.data["photo"])
                self.assertIn("/media/users/", response.data["photo"])
                self.user.refresh_from_db()
                self.assertTrue(
                    self.user.photo.name.startswith(f"users/{self.user.company_id}/")
                )

    def test_patch_photo_null_clears(self):
        import tempfile
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (1, 1), "red").save(buf, format="PNG")
        with tempfile.TemporaryDirectory() as media:
            with override_settings(MEDIA_ROOT=media):
                self.user.photo.save(
                    "avatar.png",
                    SimpleUploadedFile(
                        "avatar.png", buf.getvalue(), content_type="image/png"
                    ),
                    save=True,
                )
                response = self.client.patch(
                    self.url,
                    {"photo": None},
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertIsNone(response.data["photo"])
                self.user.refresh_from_db()
                self.assertFalse(self.user.photo)


class OutstandingTokenAdminFilterTests(APITestCase):
    """Admin filters for outstanding refresh tokens."""

    def setUp(self):
        from datetime import timedelta

        from rest_framework_simplejwt.tokens import RefreshToken
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken,
            OutstandingToken,
        )

        from accounts.admin import (
            ActiveOutstandingTokenFilter,
            ExpiredOutstandingTokenFilter,
        )

        self.OutstandingToken = OutstandingToken
        self.ActiveOutstandingTokenFilter = ActiveOutstandingTokenFilter
        self.ExpiredOutstandingTokenFilter = ExpiredOutstandingTokenFilter

        self.company = Company.objects.create(name="Token Filter Co")
        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
        )
        other = User.objects.create_user(
            phone_number="+8801712345679",
            name="Other User",
            password="strong-pass-123",
            company=self.company,
        )

        RefreshToken.for_user(self.user)
        RefreshToken.for_user(other)

        self.active = OutstandingToken.objects.get(user=self.user)
        RefreshToken.for_user(self.user)
        self.blacklisted = (
            OutstandingToken.objects.filter(user=self.user)
            .exclude(pk=self.active.pk)
            .get()
        )
        BlacklistedToken.objects.get_or_create(token=self.blacklisted)

        self.expired = OutstandingToken.objects.create(
            user=self.user,
            jti="expired-jti-for-filter-test",
            token="unused",
            created_at=timezone.now() - timedelta(days=8),
            expires_at=timezone.now() - timedelta(days=1),
        )

    def _filtered(self, filter_cls, param, value):
        filt = filter_cls(None, {param: value}, self.OutstandingToken, None)
        return list(
            filt.queryset(None, self.OutstandingToken.objects.all()).values_list(
                "pk", flat=True
            )
        )

    def test_active_yes_excludes_blacklisted_and_expired(self):
        pks = self._filtered(self.ActiveOutstandingTokenFilter, "active", "1")
        self.assertIn(self.active.pk, pks)
        self.assertNotIn(self.blacklisted.pk, pks)
        self.assertNotIn(self.expired.pk, pks)

    def test_active_no_includes_blacklisted_and_expired(self):
        pks = self._filtered(self.ActiveOutstandingTokenFilter, "active", "0")
        self.assertNotIn(self.active.pk, pks)
        self.assertIn(self.blacklisted.pk, pks)
        self.assertIn(self.expired.pk, pks)

    def test_expired_yes_only_past_expires_at(self):
        pks = self._filtered(self.ExpiredOutstandingTokenFilter, "expired", "1")
        self.assertIn(self.expired.pk, pks)
        self.assertNotIn(self.active.pk, pks)
        self.assertNotIn(self.blacklisted.pk, pks)

    def test_expired_no_excludes_past_expires_at(self):
        pks = self._filtered(self.ExpiredOutstandingTokenFilter, "expired", "0")
        self.assertNotIn(self.expired.pk, pks)
        self.assertIn(self.active.pk, pks)
        self.assertIn(self.blacklisted.pk, pks)


class OutstandingTokenBlacklistAdminTests(APITestCase):
    """Changelist bulk action: blacklist selected outstanding refresh tokens."""

    def setUp(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken,
            OutstandingToken,
        )

        self.BlacklistedToken = BlacklistedToken
        self.OutstandingToken = OutstandingToken

        self.company = Company.objects.create(name="Blacklist Admin Co")
        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
        )
        self.other = User.objects.create_user(
            phone_number="+8801712345679",
            name="Other User",
            password="strong-pass-123",
            company=self.company,
        )
        self.admin = User.objects.create_superuser(
            phone_number="+8801700000001",
            name="Staff",
            password="pass-12345",
        )
        RefreshToken.for_user(self.user)
        RefreshToken.for_user(self.other)
        self.token_a = OutstandingToken.objects.get(user=self.user)
        self.token_b = OutstandingToken.objects.get(user=self.other)
        self.client.force_login(self.admin)
        self.changelist_url = reverse(
            "admin:token_blacklist_outstandingtoken_changelist"
        )

    def _run_action(self, action, *tokens):
        return self.client.post(
            self.changelist_url,
            {
                "action": action,
                "_selected_action": [str(t.pk) for t in tokens],
            },
        )

    def test_changelist_links_user_to_user_change_page(self):
        user_change_url = reverse("admin:accounts_user_change", args=[self.user.pk])
        response = self.client.get(self.changelist_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, user_change_url)
        self.assertContains(response, self.user.name)
        self.assertContains(response, "Blacklist selected tokens")
        self.assertContains(response, "Delete selected outstanding tokens")

    def test_bulk_blacklist_selected_tokens(self):
        response = self._run_action(
            "blacklist_selected_tokens", self.token_a, self.token_b
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            self.BlacklistedToken.objects.filter(token=self.token_a).exists()
        )
        self.assertTrue(
            self.BlacklistedToken.objects.filter(token=self.token_b).exists()
        )

    def test_bulk_blacklist_skips_already_blacklisted(self):
        self.BlacklistedToken.objects.get_or_create(token=self.token_a)
        response = self._run_action(
            "blacklist_selected_tokens", self.token_a, self.token_b
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.BlacklistedToken.objects.filter(token=self.token_a).count(), 1
        )
        self.assertTrue(
            self.BlacklistedToken.objects.filter(token=self.token_b).exists()
        )

    def test_bulk_delete_selected_tokens(self):
        self.BlacklistedToken.objects.get_or_create(token=self.token_a)
        token_a_id = self.token_a.pk
        token_b_id = self.token_b.pk
        response = self._run_action(
            "delete_selected_tokens", self.token_a, self.token_b
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            self.OutstandingToken.objects.filter(pk__in=[token_a_id, token_b_id]).exists()
        )
        self.assertFalse(
            self.BlacklistedToken.objects.filter(token_id=token_a_id).exists()
        )

    def test_change_page_has_no_detail_blacklist_action(self):
        change_url = reverse(
            "admin:token_blacklist_outstandingtoken_change",
            args=[self.token_a.pk],
        )
        response = self.client.get(change_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Blacklist token")
