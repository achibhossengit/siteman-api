from rest_framework.exceptions import ValidationError

from . import status_codes

# Backward-compatible aliases (prefer status_codes.*)
SUBSCRIPTION_EXPIRED_RESPONSE_CODE = status_codes.SUBSCRIPTION_EXPIRED
SUBSCRIPTION_LIMIT_EXCEEDED_RESPONSE_CODE = status_codes.SUBSCRIPTION_LIMIT_EXCEEDED


# Internal business exceptions
class SubscriptionError(Exception):
    default_message = "Subscription error."

    def __init__(self, message=None):
        super().__init__(message or self.default_message)


class SubscriptionExpiredError(SubscriptionError):
    default_message = "Company subscription has expired."


class SubscriptionLimitExceededError(SubscriptionError):
    default_message = "Subscription limit exceeded for this company."


# DRF exceptions
class SubscriptionExpired(ValidationError):
    default_detail = "Company subscription has expired."
    default_code = status_codes.SUBSCRIPTION_EXPIRED


class SubscriptionLimitExceeded(ValidationError):
    default_detail = "Subscription limit exceeded for this company."
    default_code = status_codes.SUBSCRIPTION_LIMIT_EXCEEDED
