from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image

from apps.ai.forms import AIConfigurationForm, OCRUploadForm


def _image_upload(name="invoice.png", image_format="PNG"):
    image = Image.new("RGB", (2, 2), color="white")
    content = BytesIO()
    image.save(content, format=image_format)
    return SimpleUploadedFile(
        name, content.getvalue(), content_type=f"image/{image_format.lower()}"
    )


class OCRUploadFormTests(SimpleTestCase):
    def test_valid_image_and_document_type(self):
        form = OCRUploadForm(
            data={"doc_type": "receipt"},
            files={"file": _image_upload()},
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_rejects_missing_file(self):
        form = OCRUploadForm(data={"doc_type": "invoice"}, files={})

        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)

    def test_rejects_invalid_document_type(self):
        form = OCRUploadForm(
            data={"doc_type": "invalid"},
            files={"file": _image_upload()},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("doc_type", form.errors)

    def test_rejects_non_image_payload_even_with_image_name(self):
        form = OCRUploadForm(
            data={"doc_type": "invoice"},
            files={
                "file": SimpleUploadedFile(
                    "invoice.png", b"not an image", content_type="image/png"
                )
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)

    def test_rejects_pdf_which_ocr_service_cannot_process(self):
        form = OCRUploadForm(
            data={"doc_type": "invoice"},
            files={
                "file": SimpleUploadedFile(
                    "invoice.pdf", b"%PDF-1.4", content_type="application/pdf"
                )
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)

    def test_rejects_oversized_image(self):
        form = OCRUploadForm(
            data={"doc_type": "invoice"},
            files={
                "file": SimpleUploadedFile(
                    "invoice.png",
                    b"x" * (10 * 1024 * 1024 + 1),
                    content_type="image/png",
                )
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)


class AIConfigurationFormTests(SimpleTestCase):
    def _form(self, **overrides):
        data = {
            "ai_provider": "openai",
            "openai_model": "gpt-4o-mini",
            "temperature": "0.3",
            "max_tokens": "2048",
        }
        data.update(overrides)
        return AIConfigurationForm(data=data)

    def test_accepts_valid_numeric_settings(self):
        self.assertTrue(self._form().is_valid())

    def test_rejects_temperature_outside_supported_range(self):
        for value in ("-0.1", "2.1"):
            with self.subTest(value=value):
                form = self._form(temperature=value)
                self.assertFalse(form.is_valid())
                self.assertIn("temperature", form.errors)

    def test_rejects_invalid_token_limits(self):
        for value in ("0", "200001", "not-a-number"):
            with self.subTest(value=value):
                form = self._form(max_tokens=value)
                self.assertFalse(form.is_valid())
                self.assertIn("max_tokens", form.errors)
