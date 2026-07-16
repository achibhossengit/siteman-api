"""Central API / exception response codes."""

# Generic validation
INVALID = "invalid"
EXPIRED = "expired"

# OTP / verification
REQUIRED_EMAIL = "required_email"
ALREADY_REGISTERED = "already_registered"
RESEND_COOLDOWN = "resend_cooldown"
MAX_RESENDS = "max_resends"
MAX_ATTEMPTS = "max_attempts"

# Notifications
NOTIFICATION_DELIVERY_FAILED = "notification_delivery_failed"

# Subscription
SUBSCRIPTION_EXPIRED = "subscription_expired"
SUBSCRIPTION_LIMIT_EXCEEDED = "subscription_limit_exceeded"

# Sites
SITE_NAME_EXISTS = "site_name_exists"
SITE_CLOSED = "site_closed"
SITE_HAS_RECORDS = "site_has_records"
SITE_INACTIVE = "site_inactive"
SITE_WRONG_COMPANY = "site_wrong_company"
UNAUTHORIZED_SITE = "unauthorized_site"

# Labours
LABOUR_INACTIVE = "labour_inactive"
LABOUR_NAME_EXISTS = "labour_name_exists"

# Common
RECORD_FUTURE_DATE = "record_future_date"
RECORD_SEALED = "record_sealed"
RECORD_UNIQUE_CONSTRAINT_VIOLATION = "record_unique_constraint_violation"

# Labour payments
CATEGORY_NOT_ALLOWED = "category_not_allowed"