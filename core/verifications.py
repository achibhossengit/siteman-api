import math
import secrets
from datetime import timedelta
from uuid import uuid4
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.utils import timezone
from rest_framework.exceptions import Throttled, ValidationError

OTP_LENGTH = getattr(settings, "OTP_LENGTH", 6)
OTP_AGE = getattr(settings, "OTP_AGE", 300)
TICKET_TTL = getattr(settings, "OTP_TICKET_TTL", 3600)
RESEND_COOLDOWN = getattr(settings, "OTP_RESEND_COOLDOWN", 60)
MAX_RESENDS = getattr(settings, "OTP_MAX_RESENDS", 5)
MAX_ATTEMPTS = getattr(settings, "OTP_MAX_ATTEMPTS", 5)

REGISTER_PURPOSE = "register"


def _key(ticket):
    return f"otp:{ticket}"


def _generate_otp():
    """Generate OTP of the configured length."""
    return "".join(secrets.choice("0123456789") for _ in range(OTP_LENGTH))


def _now():
    return timezone.now()


def _load(ticket, purpose=None):
    """Load ticket data from cache."""
    data = cache.get(_key(ticket))
    if data is None:
        raise ValidationError(code="invalid", detail={"ticket": "This verification ticket is invalid."})
    if purpose is not None and data.get("purpose") != purpose:
        raise ValidationError(code="invalid", detail={"ticket": "This verification ticket is invalid."})
    return data


def _save(ticket, data):
    """Update ticket TTL and save to cache"""
    # if set the TTL as `TICKET_TTL` on every save, 
    # it will never expire if user keeps resending OTP.
    # we are overrriding the cache; so need to set the remaining TTL.
    remaining = (data["expires_at"] - _now()).total_seconds()
    if remaining <= 0:
        # this condition never meet for a new ticket
        cache.delete(_key(ticket))
        raise ValidationError(code="expired", detail={"ticket": "This verification ticket has expired."})
    cache.set(_key(ticket), data, int(remaining))


def create_ticket(purpose, channel, phone, email, payload):
    """Create new ticket, save to cache and returns ticket + delivery info.

    Both contacts are kept (either may be None) so delivery can fall back
    to the other channel and resends reproduce the same delivery info."""
    ticket = uuid4().hex
    otp = _generate_otp()
    now = _now()
    deliveryinfo = {
        "channel": channel,
        "phone": phone,
        "email": email,
        "otp": otp
    }
    data = {
        "purpose": purpose,
        "channel": channel,
        "phone": phone,
        "email": email,
        "payload": payload,
        "otp_hash": make_password(otp),
        "otp_expires_at": now + timedelta(seconds=OTP_AGE),
        "expires_at": now + timedelta(seconds=TICKET_TTL),
        "attempts": 0,
        "resend_count": 0,
        "last_sent_at": now,
    }
    _save(ticket, data)
    return ticket, deliveryinfo


def resend(ticket, purpose=None):
    """Regenerate the OTP for an existing ticket. Enforces a per-send cooldown
    and a per-ticket resend cap. Returns delivery info for notifications."""
    data = _load(ticket, purpose)
    now = _now()
    elapsed = (now - data["last_sent_at"]).total_seconds()
    
    if elapsed < RESEND_COOLDOWN:
        # This `wait` will set as response header "Retry-After" in seconds, 
        # so that client can know how long to wait before retrying.
        raise Throttled(wait=math.ceil(RESEND_COOLDOWN - elapsed), code="resend_cooldown", detail="Please wait before requesting a new code.")
    if data["resend_count"] >= MAX_RESENDS:
        raise Throttled(code="max_resends", detail="Too many code requests. Try again later.")
        
    otp = _generate_otp()
    data["otp_hash"] = make_password(otp)
    data["otp_expires_at"] = now + timedelta(seconds=OTP_AGE)
    data["resend_count"] += 1
    data["attempts"] = 0
    data["last_sent_at"] = now
    
    _save(ticket, data)
    deliveryinfo = {"channel": data["channel"], "phone": data["phone"], "email": data["email"], "otp": otp}
    return deliveryinfo


def verify(ticket, code, purpose=None):
    """Check the OTP. Consumes the ticket on success and returns its payload."""
    data = _load(ticket, purpose)
    if data["attempts"] >= MAX_ATTEMPTS:
        cache.delete(_key(ticket))
        raise ValidationError(code="max_attempts", detail="Too many invalid attempts. Request a new code.")
    if _now() > data["otp_expires_at"]:
        raise ValidationError(code="expired", detail={"otp": "This OTP has expired. Request a new one."})
    if not check_password(code, data["otp_hash"]):
        data["attempts"] += 1
        _save(ticket, data)
        raise ValidationError(code="invalid", detail={"otp": "Invalid verification OTP."})
    cache.delete(_key(ticket))
    return data["payload"]
