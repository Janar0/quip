"""Multi-provider OCR — Tesseract (local), Mistral (cloud), or auto.

Providers:
  tess — Tesseract via pytesseract. Zero cost, runs locally, needs system pkg.
         Install: `apt install tesseract-ocr tesseract-ocr-rus` or the Windows
         installer from https://github.com/UB-Mannheim/tesseract/wiki
  mistral — Mistral OCR API. Best for formulas/LaTeX, needs API key.
  auto — Try tesseract first; fall back to mistral when tesseract is
         unavailable or the result looks like a formula/table.

Configure with `ocr_provider` setting. Graceful: if a provider's deps are
missing it returns an empty result so callers (documents.py) fall back to
embedded text extraction.
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from quip.core.config import get_setting

logger = logging.getLogger(__name__)

# Bound concurrent external OCR calls — Mistral has per-account rate limits.
_cloud_semaphore = asyncio.Semaphore(4)


@dataclass
class OCRResult:
    text: str = ""
    error: str | None = None


# ── Abstract provider ─────────────────────────────────────────────────────

class BaseOCRProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def ocr_image(self, image_bytes: bytes, mime: str) -> OCRResult: ...

    async def ocr_pdf(self, pdf_bytes: bytes) -> OCRResult:
        """Default: convert first few pages to images and OCR them."""
        # Tesseract can't do PDF directly; callers that want full PDF OCR
        # should use ocr_image per page.  Subclasses may override.
        return OCRResult(error="pdf_not_supported")


# ── Tesseract (local) ─────────────────────────────────────────────────────

_TESSERACT_AVAILABLE = None  # tri-state: None=unchecked, True, False
_TESS_LANGS: list[str] | None = None  # cached available languages


def _check_tesseract() -> bool:
    global _TESSERACT_AVAILABLE
    if _TESSERACT_AVAILABLE is None:
        try:
            import pytesseract  # noqa: F401
            import PIL.Image  # noqa: F401
            _TESSERACT_AVAILABLE = True
        except ImportError:
            _TESSERACT_AVAILABLE = False
    return _TESSERACT_AVAILABLE


_IS_FORMULA_RE = (
    r'\$\$|\$[^$]+\$|'         # LaTeX delimiters
    r'\\int|\\sum|\\frac|\\sqrt|\\alpha|\\beta|\\gamma|\\delta|\\lambda|\\mu|\\sigma|'
    r'\\prod|\\infty|\\partial|\\nabla|\\leq|\\geq|\\neq|\\approx|'
    r'∫|∑|∏|√|∞|∂|∇|α|β|γ|δ|λ|μ|σ'
)


def _looks_like_formula(text: str) -> bool:
    """Heuristic: text contains LaTeX patterns or math symbols."""
    import re
    return bool(re.search(_IS_FORMULA_RE, text))


class TesseractOCR(BaseOCRProvider):
    name = "tess"

    def _lang_string(self) -> str:
        cfg = get_setting("ocr_tesseract_langs", "eng+rus")
        return cfg.replace(",", "+").replace(" ", "+")

    async def ocr_image(self, image_bytes: bytes, mime: str) -> OCRResult:
        if not _check_tesseract():
            return OCRResult(error="tesseract_not_installed")

        import pytesseract
        from PIL import Image

        loop = asyncio.get_running_loop()
        try:
            img = await loop.run_in_executor(
                None, lambda: Image.open(io.BytesIO(image_bytes)).convert("RGB")
            )
        except Exception as e:
            return OCRResult(error=f"image_open_error: {e}")

        lang = self._lang_string()
        try:
            text = await loop.run_in_executor(
                None,
                lambda: pytesseract.image_to_string(img, lang=lang, config="--psm 3"),
            )
        except pytesseract.TesseractError as e:
            # If the language pack is missing, tesseract errors immediately.
            # Try eng-only as a last resort.
            if lang != "eng":
                try:
                    text = await loop.run_in_executor(
                        None,
                        lambda: pytesseract.image_to_string(img, lang="eng"),
                    )
                except Exception:
                    return OCRResult(error=f"tesseract_error: {e}")
            else:
                return OCRResult(error=f"tesseract_error: {e}")
        except Exception as e:
            return OCRResult(error=f"tesseract_error: {e}")

        return OCRResult(text=text.strip())


# ── Mistral (cloud) ───────────────────────────────────────────────────────

_MISTRAL_OCR_URL = "https://api.mistral.ai/v1/ocr"
_MISTRAL_OCR_MODEL = "mistral-ocr-latest"


def _mistral_key() -> str:
    return get_setting("mistral_api_key", "") or os.getenv("MISTRAL_API_KEY", "")


class MistralOCR(BaseOCRProvider):
    name = "mistral"

    async def ocr_image(self, image_bytes: bytes, mime: str) -> OCRResult:
        key = _mistral_key()
        if not key:
            return OCRResult(error="no_key")
        b64 = base64.b64encode(image_bytes).decode("ascii")
        return await self._post({
            "model": _MISTRAL_OCR_MODEL,
            "document": {
                "type": "image_url",
                "image_url": f"data:{mime};base64,{b64}",
            },
        }, key)

    async def ocr_pdf(self, pdf_bytes: bytes) -> OCRResult:
        key = _mistral_key()
        if not key:
            return OCRResult(error="no_key")
        b64 = base64.b64encode(pdf_bytes).decode("ascii")
        return await self._post({
            "model": _MISTRAL_OCR_MODEL,
            "document": {
                "type": "document_url",
                "document_url": f"data:application/pdf;base64,{b64}",
            },
        }, key)

    async def _post(self, payload: dict, key: str) -> OCRResult:
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        delays = (1.0, 2.0, 4.0)
        async with _cloud_semaphore:
            for attempt, delay in enumerate((0.0,) + delays):
                if delay:
                    await asyncio.sleep(delay)
                try:
                    async with httpx.AsyncClient(timeout=30) as client:
                        r = await client.post(_MISTRAL_OCR_URL, headers=headers, json=payload)
                    if r.is_success:
                        return self._parse(r.json())
                    if 400 <= r.status_code < 500:
                        return OCRResult(error=f"http_{r.status_code}: {r.text[:200]}")
                    logger.warning(f"Mistral OCR {r.status_code}, attempt {attempt+1}")
                except (httpx.TimeoutException, httpx.NetworkError) as e:
                    logger.warning(f"Mistral OCR network error attempt {attempt+1}: {e}")
                except Exception as e:
                    logger.error(f"Mistral OCR unexpected error: {e}")
                    return OCRResult(error=str(e))
        return OCRResult(error="retry_exhausted")

    @staticmethod
    def _parse(data: dict) -> OCRResult:
        pages = data.get("pages") or []
        parts = [p.get("markdown", "") for p in pages if (p.get("markdown") or "").strip()]
        return OCRResult(text="\n\n".join(parts))


# ── Auto (tess → mistral fallback) ────────────────────────────────────────

class AutoOCR(BaseOCRProvider):
    """Try Tesseract first; escalate to Mistral for formula-heavy content."""

    name = "auto"

    async def ocr_image(self, image_bytes: bytes, mime: str) -> OCRResult:
        tess = TesseractOCR()
        res = await tess.ocr_image(image_bytes, mime)
        # If tesseract worked and result doesn't look like a formula, done
        if res.text and not _looks_like_formula(res.text):
            return res
        # Otherwise try Mistral for better quality
        mistral = MistralOCR()
        key = _mistral_key()
        if not key:
            return res  # No Mistral key — use whatever tesseract gave us
        logger.info("AutoOCR: tess gave %d chars (formula=%s), falling back to mistral",
                    len(res.text), _looks_like_formula(res.text))
        mr = await mistral.ocr_image(image_bytes, mime)
        return mr if mr.text else res  # Prefer Mistral on success, keep tess on failure

    async def ocr_pdf(self, pdf_bytes: bytes) -> OCRResult:
        # Tesseract can't do PDFs directly; go straight to Mistral if available
        mistral = MistralOCR()
        key = _mistral_key()
        if key:
            return await mistral.ocr_pdf(pdf_bytes)
        return OCRResult(error="no_provider")


# ── Provider registry ─────────────────────────────────────────────────────

_PROVIDERS: dict[str, BaseOCRProvider] = {
    "tess": TesseractOCR(),
    "mistral": MistralOCR(),
    "auto": AutoOCR(),
}


def _get_provider() -> BaseOCRProvider:
    name = get_setting("ocr_provider", "auto").lower()
    if name == "none":
        return None  # type: ignore[return-value]
    prov = _PROVIDERS.get(name)
    if prov is None:
        logger.warning(f"Unknown ocr_provider={name!r}, falling back to auto")
        prov = _PROVIDERS["auto"]
    return prov


# ── Public API (backwards-compat wrappers) ────────────────────────────────

async def ocr_image(image_bytes: bytes, mime: str) -> OCRResult:
    """Run OCR on a single image using the configured provider."""
    prov = _get_provider()
    if prov is None:
        return OCRResult(error="ocr_disabled")
    name = prov.name
    try:
        res = await prov.ocr_image(image_bytes, mime)
        logger.debug("OCR (%s): %d chars, error=%s", name, len(res.text), res.error)
        return res
    except Exception as e:
        logger.error("OCR (%s) exception: %s", name, e)
        return OCRResult(error=str(e))


async def ocr_pdf(pdf_bytes: bytes) -> OCRResult:
    """Run OCR on a PDF using the configured provider."""
    prov = _get_provider()
    if prov is None:
        return OCRResult(error="ocr_disabled")
    try:
        return await prov.ocr_pdf(pdf_bytes)
    except Exception as e:
        logger.error("OCR (%s) exception: %s", prov.name, e)
        return OCRResult(error=str(e))
