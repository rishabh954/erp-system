from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

MAX_OCR_UPLOAD_SIZE = 10 * 1024 * 1024


def validate_ocr_image(uploaded_file):
    if uploaded_file.size > MAX_OCR_UPLOAD_SIZE:
        raise ValidationError("Image must be 10 MB or smaller.")

    try:
        with Image.open(uploaded_file) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValidationError("Upload a JPEG, PNG, or WebP image.")
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ValidationError("Upload a valid image file.") from None
    finally:
        uploaded_file.seek(0)
