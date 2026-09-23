"""Bound local OCR work so one image cannot consume a worker indefinitely."""

from io import BytesIO

import pytest
from PIL import Image

from quip.services.ocr import TesseractOCR


@pytest.mark.asyncio
async def test_tesseract_process_has_a_finite_deadline(monkeypatch):
    image = BytesIO()
    Image.new("RGB", (8, 8), "white").save(image, format="PNG")

    def recognize(_image, *, lang, config, timeout=None):
        if timeout is None or not 0 < timeout <= 30:
            raise RuntimeError("OCR subprocess has no short deadline")
        return "bounded text"

    monkeypatch.setattr("pytesseract.image_to_string", recognize)
    result = await TesseractOCR().ocr_image(image.getvalue(), "image/png")

    assert result.text == "bounded text"
