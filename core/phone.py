import re
from django.core.exceptions import ValidationError

BD_PHONE_RE = re.compile(r"^(?:\+?880|0)?(1[3-9]\d{8})$")


def normalize_bd_phone(raw):
    """Normalize a Bangladeshi mobile number to +8801XXXXXXXXX.

    Accepts 01XXXXXXXXX, 1XXXXXXXXX, 8801XXXXXXXXX or +8801XXXXXXXXX.
    Raises ValidationError on an invalid operator code or shape.
    """
    if not raw:
        raise ValidationError("Phone number is required.")
    cleaned = re.sub(r"[\s\-()]", "", str(raw))
    match = BD_PHONE_RE.match(cleaned)
    if not match:
        raise ValidationError("Enter a valid Bangladeshi phone number.")
    return "+880" + match.group(1)


def format_bd_phone_local(phone):
    """Format a stored BD mobile as 01XXXXXXXXX for API responses.

    Returns the original value unchanged if it is empty or not a valid BD mobile.
    """
    if not phone:
        return phone
    cleaned = re.sub(r"[\s\-()]", "", str(phone))
    match = BD_PHONE_RE.match(cleaned)
    if not match:
        return phone
    return "0" + match.group(1)
