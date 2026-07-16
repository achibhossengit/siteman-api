import logging
from dataclasses import dataclass
from rest_framework import status
from rest_framework.exceptions import APIException

from . import status_codes

logger = logging.getLogger("siteman.notifications")

SMS = "sms"
EMAIL = "email"

class NotificationDeliveryError(APIException):
    """The notification could not be delivered on any usable channel."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Could not send the notification. Please try again later."
    default_code = status_codes.NOTIFICATION_DELIVERY_FAILED


@dataclass
class Notification:
    body: str
    phone: str = None
    email: str = None
    subject: str = ""  # email only
    channel: str = SMS  # preferred channel: "sms" or "email"


def send(notification, immediate=True):
    """MVP delivery: log the message as an SMS. Real SMS/email providers,
    channel routing and broker-backed scheduled sends come post-MVP."""
    try:
        if immediate:
            logger.info("[SMS] to=%s | %s", notification.phone, notification.body)
            return True
        else:
            # Celery phase: enqueue a task instead of sending immediately.
            raise NotImplementedError("Scheduled delivery not yet implemented.")
    except Exception as e:
        logger.exception("Notification delivery failed: %s", e)
        raise NotificationDeliveryError()


def deliver_otp(channel, phone, email, otp, *args, **kwargs):
    """Send an OTP. `channel`/`email` are accepted (tickets already carry
    them) but MVP delivery is SMS-log only."""
    message = f"Your SiteMan verification code is {otp}. Do not share it with anyone."
    notification = Notification(
        body=message,
        phone=phone,
        email=email,
        subject="SiteMan verification code",
        channel=channel,
    )
    return send(notification, immediate=True)
