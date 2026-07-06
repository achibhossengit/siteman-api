from unittest.mock import patch
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle
from core import verifications
from company.models import Company
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
