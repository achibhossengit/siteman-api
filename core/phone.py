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
