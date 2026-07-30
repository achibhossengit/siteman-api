import logging
from dataclasses import dataclass
from django.conf import settings
from django.core.mail import send_mail
from rest_framework import status
from rest_framework.exceptions import APIException

from . import status_codes

logger = logging.getLogger("siteman.notifications")


class NotificationDeliveryError(APIException):
    """The email notification could not be delivered."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Could not send the notification. Please try again later."
    default_code = status_codes.NOTIFICATION_DELIVERY_FAILED


@dataclass
class Notification:
    body: str
    email: str
    subject: str


def send(notification, immediate=True):
    """Send an email immediately through Django's configured backend."""
    try:
        if not immediate:
            raise NotImplementedError("Scheduled delivery not yet implemented.")

        if not notification.email:
            raise ValueError("Email recipient is required.")

        sent_count = send_mail(
            subject=notification.subject,
            message=notification.body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[notification.email],
            fail_silently=False,
        )
        if sent_count != 1:
            raise RuntimeError("Email was not accepted for delivery.")
        return True
    except Exception as exc:
        logger.exception("Email delivery failed: %s", exc)
        raise NotificationDeliveryError() from exc


def deliver_otp(email, otp, **kwargs):
    """Send an OTP to the ticket's verified email address."""
    message = f"Your SiteMan verification code is {otp}. Do not share it with anyone."
    notification = Notification(
        body=message,
        email=email,
        subject="SiteMan verification code",
    )
    return send(notification, immediate=True)
