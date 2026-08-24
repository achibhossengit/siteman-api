from unittest.mock import patch

from django.conf import settings
from django.core import mail
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .notifications import NotificationDeliveryError, deliver_otp


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="SiteMan <otp@example.com>",
)
class EmailNotificationTests(SimpleTestCase):
    def test_deliver_otp_sends_email(self):
        result = deliver_otp(
            email="user@example.com",
            otp="123456",
        )

        self.assertTrue(result)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["user@example.com"])
        self.assertEqual(message.subject, "SiteMan verification code")
        self.assertIn("123456", message.body)

    @patch("core.notifications.logger.exception")
    @patch("core.notifications.send_mail", side_effect=RuntimeError("provider down"))
    def test_delivery_failure_returns_service_unavailable_error(
        self, _send_mail, _logger_exception
    ):
        with self.assertRaises(NotificationDeliveryError):
            deliver_otp(email="user@example.com", otp="123456")

    @patch("core.notifications.logger.exception")
    def test_missing_email_returns_service_unavailable_error(self, _logger_exception):
        with self.assertRaises(NotificationDeliveryError):
            deliver_otp(email=None, otp="123456")


class AdminUrlTests(TestCase):
    def test_admin_mounted_at_configured_path(self):
        self.assertEqual(reverse("admin:index"), f"/{settings.ADMIN_URL}")

    def test_default_admin_path_is_not_mounted(self):
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 404)

    def test_configured_admin_path_redirects_to_login(self):
        response = self.client.get(f"/{settings.ADMIN_URL}")
        self.assertEqual(response.status_code, 302)
        self.assertIn(f"/{settings.ADMIN_URL}login/", response["Location"])


class ProfilePhotoPrepareTests(SimpleTestCase):
    def test_resize_caps_longest_edge(self):
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        from core.images import MAX_EDGE, resize_profile_photo

        buf = BytesIO()
        Image.new("RGB", (800, 600), "navy").save(buf, format="JPEG")
        upload = SimpleUploadedFile(
            "wide.jpg", buf.getvalue(), content_type="image/jpeg"
        )
        result = resize_profile_photo(upload)
        with Image.open(result) as image:
            self.assertEqual(max(image.size), MAX_EDGE)
            self.assertEqual(image.size, (447, 335))
            self.assertEqual(image.format, "JPEG")

    def test_small_image_is_not_upscaled(self):
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        from core.images import resize_profile_photo

        buf = BytesIO()
        Image.new("RGB", (40, 40), "red").save(buf, format="PNG")
        upload = SimpleUploadedFile(
            "tiny.png", buf.getvalue(), content_type="image/png"
        )
        result = resize_profile_photo(upload)
        with Image.open(result) as image:
            self.assertEqual(image.size, (40, 40))
