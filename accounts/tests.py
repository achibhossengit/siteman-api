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

TEST_CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
}
TEST_THROTTLE_RATES = {
    "register": "1000/min",
    "login": "1000/min",
    "password_reset": "1000/min",
    "user": "1000/min",
}


@override_settings(CACHES=TEST_CACHES)
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
        self.assertEqual(mocked.call_args.kwargs["phone"], "+8801712345678")

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


@override_settings(CACHES=TEST_CACHES)
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
            "company_name": "Achib Builders",
            "password": "strong-pass-123",
        }
        self.reset_payload = {"phone_number": "+8801712345678", "name": "Achib Hossen"}

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
            password="old-pass-123",
            company=self.company,
        )

    def request_reset(self, phone="+8801712345678", name="Achib Hossen"):
        """POST /password/reset with delivery mocked.
        Returns (response, ticket, otp, mocked)."""
        with patch("core.notifications.deliver_otp") as mocked:
            response = self.client.post(
                self.reset_url, {"phone_number": phone, "name": name}
            )
        ticket = response.data.get("ticket") if response.status_code == 200 else None
        otp = mocked.call_args.kwargs.get("otp") if mocked.call_args else None
        return response, ticket, otp, mocked

    # --- request ---

    def test_reset_request_sends_otp_for_registered_phone(self):
        response, ticket, _, mocked = self.request_reset()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(response.data.keys(), ["ticket", "otp_expires_in", "resend_cooldown"])
        self.assertIsNotNone(ticket)
        mocked.assert_called_once()
        self.assertEqual(mocked.call_args.kwargs["phone"], "+8801712345678")

    def test_reset_request_invalid_phone_same_response_no_delivery(self):
        response, ticket, _, mocked = self.request_reset(phone="+8801912345678")
        # identical 200 body — the caller can not tell the phone is unregistered
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(response.data.keys(), ["ticket", "otp_expires_in", "resend_cooldown"])
        self.assertIsNotNone(ticket)
        mocked.assert_not_called()

    def test_reset_request_inactive_or_deleted_user_gets_ghost_ticket(self):
        cases = {"is_active": False, "deleted_at": timezone.now()}
        for field, value in cases.items():
            with self.subTest(field=field):
                User.objects.filter(pk=self.user.pk).update(is_active=True, deleted_at=None)
                User.objects.filter(pk=self.user.pk).update(**{field: value})
                response, _, _, mocked = self.request_reset()
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                mocked.assert_not_called()

    def test_reset_request_rejects_invalid_phone(self):
        response, _, _, _ = self.request_reset(phone="+8802123456789")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reset_request_rejects_invalid_name_same_response_no_delivery(self):
        response, ticket, _, mocked = self.request_reset(name="Someone Else")
        # same 200 body as a valid pair — name mismatch is not revealed
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(response.data.keys(), ["ticket", "otp_expires_in", "resend_cooldown"])
        self.assertIsNotNone(ticket)
        mocked.assert_not_called()

    def test_reset_request_name_trims_surrounding_spaces(self):
        # DRF CharField trims leading/trailing whitespace by default
        _, _, _, mocked = self.request_reset(name="  Achib Hossen  ")
        mocked.assert_called_once()

    def test_reset_request_name_match_is_exact(self):
        for name in ["ACHIB HOSSEN", "achib hossen", "Achib  Hossen"]:
            with self.subTest(name=name):
                cache.clear()  # reset throttle/ticket state between attempts
                _, _, _, mocked = self.request_reset(name=name)
                mocked.assert_not_called()

    def test_reset_request_normalizes_phone(self):
        _, _, _, mocked = self.request_reset(phone="01712345678")
        self.assertEqual(mocked.call_args.kwargs["phone"], "+8801712345678")

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
            purpose=REGISTER_PURPOSE, channel="sms",
            phone="+8801712345678", email=None, payload={},
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
            purpose=PASSWORD_RESET_PURPOSE, channel="sms",
            phone=None, email=None, payload={"user_id": None},
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
                "password": "strong-pass-123",
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
    def test_list_includes_self(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], self.user.pk)

    def test_create_user_success(self):
        response = self.client.post(
            self.list_url,
            {
                "name": "Site Manager",
                "phone_number": "01711112222",
                "email": "manager@example.com",
                "password": "strong-pass-123",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "Site Manager")
        self.assertEqual(response.data["phone_number"], "+8801711112222")
        self.assertEqual(response.data["email"], "manager@example.com")
        self.assertEqual(response.data["company"], self.company.pk)
        self.assertTrue(response.data["is_active"])
        self.assertFalse(response.data["is_companyadmin"])
        self.assertNotIn("password", response.data)

        created = User.objects.get(pk=response.data["id"])
        self.assertTrue(created.check_password("strong-pass-123"))
        self.assertFalse(created.is_staff)
        self.assertFalse(created.is_superuser)

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
        self.assertEqual(len(response.data), 2)
        self.assertCountEqual(
            response.data[0].keys(),
            [
                "id",
                "name",
                "phone_number",
                "email",
                "is_active",
                "is_companyadmin",
            ],
        )
        ids = {row["id"] for row in response.data}
        self.assertIn(other.pk, ids)

    def test_retrieve_user_detail(self):
        other = self._create_company_user(name="Detail User", phone="+8801711114444")
        response = self.client.get(self._detail_url(other.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Detail User")
        self.assertIn("company", response.data)
        self.assertNotIn("password", response.data)

    def test_patch_name_email_and_is_active(self):
        other = self._create_company_user(
            name="Old Name",
            phone="+8801711115555",
            email="old@example.com",
        )
        response = self.client.patch(
            self._detail_url(other.pk),
            {
                "name": "New Name",
                "email": "new@example.com",
                "is_active": False,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "New Name")
        self.assertEqual(response.data["email"], "new@example.com")
        self.assertFalse(response.data["is_active"])
        other.refresh_from_db()
        self.assertEqual(other.name, "New Name")
        self.assertFalse(other.is_active)
        self.assertTrue(other.check_password("strong-pass-123"))

    def test_patch_ignores_phone_and_password(self):
        other = self._create_company_user(phone="+8801711116666")
        response = self.client.patch(
            self._detail_url(other.pk),
            {
                "phone_number": "+8801799999999",
                "password": "hijacked-pass-999",
                "name": "Still Karim",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        other.refresh_from_db()
        self.assertEqual(other.phone_number, "+8801711116666")
        self.assertTrue(other.check_password("strong-pass-123"))
        self.assertEqual(other.name, "Still Karim")

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

    def test_delete_not_allowed(self):
        other = self._create_company_user(phone="+8801711119999")
        response = self.client.delete(self._detail_url(other.pk))
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertTrue(User.objects.filter(pk=other.pk).exists())


class UserValidationTests(UserAPITestCase):
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

    def test_weak_password_rejected(self):
        response = self.client.post(
            self.list_url,
            {
                "name": "Weak",
                "phone_number": "+8801711121111",
                "password": "123",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class UserFilterIsolationTests(UserAPITestCase):
    def test_cannot_see_other_company_users(self):
        other = Company.objects.create(name="Other Co")
        User.objects.create_user(
            phone_number="+8801811111111",
            name="Foreign",
            password="strong-pass-123",
            company=other,
        )
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], self.user.pk)

    def test_filter_by_is_active(self):
        active = self._create_company_user(name="Active", phone="+8801711122222")
        inactive = self._create_company_user(
            name="Inactive", phone="+8801711123333", is_active=False
        )
        response = self.client.get(self.list_url, {"is_active": "true"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.data}
        self.assertIn(self.user.pk, ids)
        self.assertIn(active.pk, ids)
        self.assertNotIn(inactive.pk, ids)

    def test_search_by_name(self):
        self._create_company_user(name="Karim Mia", phone="+8801711124444")
        self._create_company_user(name="Rahim Uddin", phone="+8801711125555")
        response = self.client.get(self.list_url, {"search": "Karim"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "Karim Mia")


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


class UserGroupAPITestCase(APITestCase):
    """Shared fixtures for nested ``/users/<pk>/groups``."""

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
        self._grant_group_permissions(self.user)
        self.client.force_authenticate(user=self.user)

        self.target = User.objects.create_user(
            phone_number="+8801711111111",
            name="Karim",
            password="strong-pass-123",
            company=self.company,
        )
        self.site_manager = Group.objects.get(name="Site Manager")
        self.site_auditor = Group.objects.get(name="Site Auditor")
        self.company_admin = Group.objects.get(name="Company Admin")
        self.list_url = self._list_url(self.target.pk)

    def _grant_group_permissions(self, user, codenames=None):
        codenames = codenames or [
            "view_group",
            "add_group",
            "change_group",
            "delete_group",
        ]
        ct = ContentType.objects.get_for_model(Group)
        perms = Permission.objects.filter(content_type=ct, codename__in=codenames)
        user.user_permissions.add(*perms)

    def _list_url(self, user_id):
        return reverse(
            "user-group-list",
            kwargs={"version": "v1", "user_pk": user_id},
        )

    def _detail_url(self, user_id, group_id):
        return reverse(
            "user-group-detail",
            kwargs={"version": "v1", "user_pk": user_id, "pk": group_id},
        )


class UserGroupAuthPermissionTests(UserGroupAPITestCase):
    def test_unauthenticated_list_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_view_permission_returns_403(self):
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_add_permission_returns_403(self):
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_group_permissions(self.user, ["view_group"])
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.list_url, {"id": self.site_manager.pk})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_delete_permission_returns_403(self):
        self.target.groups.add(self.site_manager)
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_group_permissions(self.user, ["view_group", "add_group"])
        self.client.force_authenticate(user=self.user)
        response = self.client.delete(
            self._detail_url(self.target.pk, self.site_manager.pk)
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_other_company_user_returns_404(self):
        other = Company.objects.create(name="Other Co")
        foreign = User.objects.create_user(
            phone_number="+8801811111111",
            name="Foreign",
            password="strong-pass-123",
            company=other,
        )
        response = self.client.get(self._list_url(foreign.pk))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class UserGroupCRUDTests(UserGroupAPITestCase):
    def test_list_empty(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_assign_group_success(self):
        response = self.client.post(self.list_url, {"id": self.site_manager.pk})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["id"], self.site_manager.pk)
        self.assertEqual(response.data["name"], "Site Manager")
        self.assertTrue(self.target.groups.filter(pk=self.site_manager.pk).exists())

    def test_list_assigned_groups(self):
        self.target.groups.add(self.site_manager, self.site_auditor)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertCountEqual(
            [row["name"] for row in response.data],
            ["Site Auditor", "Site Manager"],
        )

    def test_assign_is_idempotent(self):
        self.target.groups.add(self.site_manager)
        response = self.client.post(self.list_url, {"id": self.site_manager.pk})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.target.groups.filter(pk=self.site_manager.pk).count(), 1)

    def test_assign_unknown_group_rejected(self):
        other = Group.objects.create(name="Random Role")
        response = self.client.post(self.list_url, {"id": other.pk})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_remove_group_success(self):
        self.target.groups.add(self.site_manager)
        response = self.client.delete(
            self._detail_url(self.target.pk, self.site_manager.pk)
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(self.target.groups.filter(pk=self.site_manager.pk).exists())

    def test_remove_unassigned_group_returns_404(self):
        response = self.client.delete(
            self._detail_url(self.target.pk, self.site_manager.pk)
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_assign_company_admin_does_not_set_flag(self):
        response = self.client.post(self.list_url, {"id": self.company_admin.pk})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_companyadmin)

    def test_remove_company_admin_does_not_clear_flag(self):
        self.target.groups.add(self.company_admin)
        self.target.is_companyadmin = True
        self.target.save(update_fields=["is_companyadmin"])

        response = self.client.delete(
            self._detail_url(self.target.pk, self.company_admin.pk)
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_companyadmin)

    def test_patch_not_allowed(self):
        self.target.groups.add(self.site_manager)
        response = self.client.patch(
            self._detail_url(self.target.pk, self.site_manager.pk),
            {"name": "Nope"},
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class UserSiteAPITestCase(APITestCase):
    """Shared fixtures for nested ``/users/<pk>/sites``."""

    def setUp(self):
        self.company = Company.objects.create(name="Achib Builders")
        self.subscription = Subscription.objects.get(company=self.company)

        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
            is_companyadmin=True,
        )
        self._grant_usersite_permissions(self.user)
        self.client.force_authenticate(user=self.user)

        self.target = User.objects.create_user(
            phone_number="+8801711111111",
            name="Karim",
            password="strong-pass-123",
            company=self.company,
        )
        self.site = Site.objects.create(
            name="Padma Bridge",
            company=self.company,
            created_by=self.user,
        )
        self.other_site = Site.objects.create(
            name="Jamuna Bridge",
            company=self.company,
            created_by=self.user,
        )
        self.list_url = self._list_url(self.target.pk)

    def _grant_usersite_permissions(self, user, codenames=None):
        codenames = codenames or [
            "view_usersite",
            "add_usersite",
            "change_usersite",
            "delete_usersite",
        ]
        ct = ContentType.objects.get_for_model(UserSite)
        perms = Permission.objects.filter(content_type=ct, codename__in=codenames)
        user.user_permissions.add(*perms)

    def _list_url(self, user_id):
        return reverse(
            "user-site-list",
            kwargs={"version": "v1", "user_pk": user_id},
        )

    def _detail_url(self, user_id, usersite_id):
        return reverse(
            "user-site-detail",
            kwargs={"version": "v1", "user_pk": user_id, "pk": usersite_id},
        )

    def _assign(self, user=None, site=None):
        return UserSite.objects.create(
            user=user or self.target,
            site=site or self.site,
            company=self.company,
            created_by=self.user,
        )


class UserSiteAuthPermissionTests(UserSiteAPITestCase):
    def test_unauthenticated_list_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_view_permission_returns_403(self):
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_add_permission_returns_403(self):
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_usersite_permissions(self.user, ["view_usersite"])
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.list_url, {"site": self.site.pk})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_delete_permission_returns_403(self):
        assignment = self._assign()
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_usersite_permissions(self.user, ["view_usersite", "add_usersite"])
        self.client.force_authenticate(user=self.user)
        response = self.client.delete(
            self._detail_url(self.target.pk, assignment.pk)
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_other_company_user_returns_404(self):
        other = Company.objects.create(name="Other Co")
        foreign = User.objects.create_user(
            phone_number="+8801811111111",
            name="Foreign",
            password="strong-pass-123",
            company=other,
        )
        response = self.client.get(self._list_url(foreign.pk))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class UserSiteCRUDTests(UserSiteAPITestCase):
    def test_list_empty(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_assign_site_success(self):
        response = self.client.post(self.list_url, {"site": self.site.pk})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["user"], self.target.pk)
        self.assertEqual(response.data["site"], self.site.pk)
        self.assertTrue(
            UserSite.objects.filter(user=self.target, site=self.site).exists()
        )

    def test_list_assigned_sites(self):
        self._assign(site=self.site)
        self._assign(site=self.other_site)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertCountEqual(
            [row["site"] for row in response.data],
            [self.site.pk, self.other_site.pk],
        )

    def test_assign_is_idempotent(self):
        self._assign()
        response = self.client.post(self.list_url, {"site": self.site.pk})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            UserSite.objects.filter(user=self.target, site=self.site).count(),
            1,
        )

    def test_assign_other_company_site_rejected(self):
        other = Company.objects.create(name="Other Co")
        foreign_site = Site.objects.create(
            name="Foreign Site",
            company=other,
            created_by=self.user,
        )
        response = self.client.post(self.list_url, {"site": foreign_site.pk})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_remove_assignment_success(self):
        assignment = self._assign()
        response = self.client.delete(
            self._detail_url(self.target.pk, assignment.pk)
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(UserSite.objects.filter(pk=assignment.pk).exists())

    def test_remove_missing_assignment_returns_404(self):
        response = self.client.delete(self._detail_url(self.target.pk, 99999))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_not_allowed(self):
        assignment = self._assign()
        response = self.client.patch(
            self._detail_url(self.target.pk, assignment.pk),
            {"site": self.other_site.pk},
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class SiteNestedUserSiteAPITestCase(APITestCase):
    """Shared fixtures for nested ``/sites/<pk>/users`` (same UserSiteViewSet)."""

    def setUp(self):
        self.company = Company.objects.create(name="Achib Builders")
        self.subscription = Subscription.objects.get(company=self.company)

        self.user = User.objects.create_user(
            phone_number="+8801712345678",
            name="Achib Hossen",
            password="strong-pass-123",
            company=self.company,
            is_companyadmin=True,
        )
        self._grant_usersite_permissions(self.user)
        self.client.force_authenticate(user=self.user)

        self.site = Site.objects.create(
            name="Padma Bridge",
            company=self.company,
            created_by=self.user,
        )
        self.target = User.objects.create_user(
            phone_number="+8801711111111",
            name="Karim",
            password="strong-pass-123",
            company=self.company,
        )
        self.other_user = User.objects.create_user(
            phone_number="+8801711112222",
            name="Rahim",
            password="strong-pass-123",
            company=self.company,
        )
        self.list_url = self._list_url(self.site.pk)

    def _grant_usersite_permissions(self, user, codenames=None):
        codenames = codenames or [
            "view_usersite",
            "add_usersite",
            "change_usersite",
            "delete_usersite",
        ]
        ct = ContentType.objects.get_for_model(UserSite)
        perms = Permission.objects.filter(content_type=ct, codename__in=codenames)
        user.user_permissions.add(*perms)

    def _list_url(self, site_id):
        return reverse(
            "site-user-list",
            kwargs={"version": "v1", "site_pk": site_id},
        )

    def _detail_url(self, site_id, usersite_id):
        return reverse(
            "site-user-detail",
            kwargs={"version": "v1", "site_pk": site_id, "pk": usersite_id},
        )

    def _assign(self, user=None, site=None):
        return UserSite.objects.create(
            user=user or self.target,
            site=site or self.site,
            company=self.company,
            created_by=self.user,
        )


class SiteNestedUserSiteAuthPermissionTests(SiteNestedUserSiteAPITestCase):
    def test_unauthenticated_list_returns_401(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_view_permission_returns_403(self):
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_add_permission_returns_403(self):
        self.user.user_permissions.clear()
        self.user = User.objects.get(pk=self.user.pk)
        self._grant_usersite_permissions(self.user, ["view_usersite"])
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.list_url, {"user": self.target.pk})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_other_company_site_returns_404(self):
        other = Company.objects.create(name="Other Co")
        foreign_site = Site.objects.create(
            name="Foreign Site",
            company=other,
            created_by=self.user,
        )
        response = self.client.get(self._list_url(foreign_site.pk))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class SiteNestedUserSiteCRUDTests(SiteNestedUserSiteAPITestCase):
    def test_list_empty(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_assign_user_success(self):
        response = self.client.post(self.list_url, {"user": self.target.pk})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["user"], self.target.pk)
        self.assertEqual(response.data["site"], self.site.pk)
        self.assertTrue(
            UserSite.objects.filter(user=self.target, site=self.site).exists()
        )

    def test_list_assigned_users(self):
        self._assign(user=self.target)
        self._assign(user=self.other_user)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertCountEqual(
            [row["user"] for row in response.data],
            [self.target.pk, self.other_user.pk],
        )

    def test_assign_is_idempotent(self):
        self._assign()
        response = self.client.post(self.list_url, {"user": self.target.pk})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            UserSite.objects.filter(user=self.target, site=self.site).count(),
            1,
        )

    def test_assign_other_company_user_rejected(self):
        other = Company.objects.create(name="Other Co")
        foreign = User.objects.create_user(
            phone_number="+8801811111111",
            name="Foreign",
            password="strong-pass-123",
            company=other,
        )
        response = self.client.post(self.list_url, {"user": foreign.pk})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_remove_assignment_success(self):
        assignment = self._assign()
        response = self.client.delete(
            self._detail_url(self.site.pk, assignment.pk)
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(UserSite.objects.filter(pk=assignment.pk).exists())

    def test_remove_missing_assignment_returns_404(self):
        response = self.client.delete(self._detail_url(self.site.pk, 99999))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_not_allowed(self):
        assignment = self._assign()
        response = self.client.patch(
            self._detail_url(self.site.pk, assignment.pk),
            {"user": self.other_user.pk},
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
