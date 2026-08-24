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
