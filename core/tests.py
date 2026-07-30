from unittest.mock import patch

from django.core import mail
from django.test import SimpleTestCase, override_settings

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
