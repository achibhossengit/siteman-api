"""Profile / labour photo upload: size cap, then longest-edge resize."""

from io import BytesIO
from pathlib import Path

from django.core.files.uploadedfile import InMemoryUploadedFile
from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework import serializers

from core import status_codes

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_EDGE = 447
JPEG_QUALITY = 85


def resize_profile_photo(uploaded_file):
    """Return a JPEG whose longest side is at most MAX_EDGE."""
    uploaded_file.seek(0)
    try:
        image = Image.open(uploaded_file)
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise serializers.ValidationError(
            "Upload a valid image (JPEG, PNG, or WebP).",
            code=status_codes.INVALID,
        ) from exc

    image = ImageOps.exif_transpose(image)
    image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)

    if image.mode in {"RGBA", "LA", "P"}:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")

    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    buffer.seek(0)

    stem = Path(getattr(uploaded_file, "name", "photo")).stem or "photo"
    name = f"{stem}.jpg"
    return InMemoryUploadedFile(
        buffer,
        field_name=None,
        name=name,
        content_type="image/jpeg",
        size=buffer.getbuffer().nbytes,
        charset=None,
    )


class ProfilePhotoField(serializers.ImageField):
    """Reject uploads over 5 MB, then resize to a 447px longest edge."""

    def to_internal_value(self, data):
        size = getattr(data, "size", None)
        if size is not None and size > MAX_UPLOAD_BYTES:
            raise serializers.ValidationError(
                "Photo must be 5 MB or smaller.",
                code=status_codes.PHOTO_TOO_LARGE,
            )
        file = super().to_internal_value(data)
        return resize_profile_photo(file)


LEDGER_FILE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
LEDGER_FILE_CONTENT_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "application/pdf",
}


class SiteCashFileField(serializers.FileField):
    """JPEG/PNG/WebP/PDF, 5 MB cap. Images are not resized (receipts stay readable)."""

    def to_internal_value(self, data):
        size = getattr(data, "size", None)
        if size is not None and size > MAX_UPLOAD_BYTES:
            raise serializers.ValidationError(
                "File must be 5 MB or smaller.",
                code=status_codes.FILE_TOO_LARGE,
            )
        uploaded = super().to_internal_value(data)
        name = getattr(uploaded, "name", "") or ""
        ext = Path(name).suffix.lower()
        content_type = (getattr(uploaded, "content_type", None) or "").lower()
        if ext not in LEDGER_FILE_EXTS:
            raise serializers.ValidationError(
                "Upload a JPEG, PNG, WebP, or PDF.",
                code=status_codes.INVALID,
            )
        if content_type and content_type not in LEDGER_FILE_CONTENT_TYPES:
            raise serializers.ValidationError(
                "Upload a JPEG, PNG, WebP, or PDF.",
                code=status_codes.INVALID,
            )
        return uploaded
