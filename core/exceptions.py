from rest_framework.exceptions import ValidationError

# Internal business exceptions
class SubscriptionError(Exception):
    default_message = "Subscription error."
    
    def __init__(self, message=None):
        super().__init__(message or self.default_message)

class SubscriptionExpiredError(SubscriptionError):
    default_message = "Company subscription has expired."

class SubscriptionLimitExceededError(SubscriptionError):
    default_message = "Open site limit exceeded for this company subscription."


# DRF exceptions
class SubscriptionExpired(ValidationError):
    default_detail = "Company subscription has expired."
    default_code = "subscription_expired"

class SubscriptionLimitExceeded(ValidationError):
    default_detail = "Open site limit exceeded for this company subscription."
    default_code = "subscription_limit_exceeded"