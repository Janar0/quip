"""Image generation service — calls OpenRouter image models (Gemini Nano Banana series)."""
import base64
import uuid
from pathlib import Path

import httpx

from quip.providers.openrouter import OPENROUTER_BASE, OPENROUTER_API_KEY

GENERATED_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "generated"


async def generate_image(
    prompt: str,
    image_urls: list[str] | None = None,
    aspect_ratio: str = "1:1",
    image_size: str = "1K",
    model: str = "",
    api_key: str = "",
    db=None,
) -> dict:
    """Call OpenRouter image generation and save the result to disk.

    Returns:
        {
            "generated_image": True,
            "url": "/api/images/{filename}",
            "urls": ["/api/images/{filename}", ...],
            "text": model's text response,
            "model": model used,
        }
    """
    key = api_key or OPENROUTER_API_KEY
    if not key:
        raise ValueError("No OpenRouter API key configured. Set it in Admin > Settings.")

    if not model:
        model = "google/gemini-2.0-flash-exp:free"

    # Build multimodal content
    content: list[dict] = []

    if image_urls:
        for url in image_urls:
            img_data = await _read_image_to_base64(url, db)
            if img_data:
                mime, b64data = img_data
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64data}"},
                })

    content.append({"type": "text", "text": prompt})

    body: dict = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "modalities": ["text", "image"],
    }

    # Image config
    image_config: dict = {}
    if aspect_ratio:
        image_config["aspect_ratio"] = aspect_ratio
    if image_size:
        image_config["image_size"] = image_size
    if image_config:
        body["image_config"] = image_config

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/Janar0/quip",
        "X-Title": "QUIP",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=15.0)) as client:
        resp = await client.post(
            f"{OPENROUTER_BASE}/chat/completions",
            json=body,
            headers=headers,
        )
        if resp.status_code != 200:
            try:
                err = resp.json()
                msg = err.get("error", {}).get("message", f"HTTP {resp.status_code}")
            except Exception:
                msg = f"HTTP {resp.status_code}: {resp.text[:500]}"
            raise ValueError(f"Image generation failed: {msg}")

        data = resp.json()

    choices = data.get("choices", [])
    if not choices:
        raise ValueError("No choices in image generation response")

    message = choices[0].get("message", {})

    # Extract text response
    msg_content = message.get("content", "")
    if isinstance(msg_content, str):
        text_response = msg_content
    elif isinstance(msg_content, list):
        text_response = " ".join(
            p.get("text", "") for p in msg_content if p.get("type") == "text"
        )
    else:
        text_response = ""

    # Extract images: try message.images first (native format), then content array
    images = message.get("images", [])
    if not images and isinstance(msg_content, list):
        images = [
            {"image_url": {"url": p["image_url"]["url"]}}
            for p in msg_content
            if p.get("type") == "image_url" and p.get("image_url", {}).get("url")
        ]

    if not images:
        raise ValueError("No images returned by the model. Try a different prompt or model.")

    # Save to disk
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    saved_urls: list[str] = []

    for img in images:
        img_url = img.get("image_url", {}).get("url", "")
        if not img_url:
            continue

        if img_url.startswith("data:"):
            header, _, b64data = img_url.partition(",")
            ext = "png"
            if "jpeg" in header or "jpg" in header:
                ext = "jpg"
            elif "webp" in header:
                ext = "webp"
            img_bytes = base64.b64decode(b64data)
        else:
            # Shouldn't happen but handle gracefully
            try:
                async with httpx.AsyncClient(timeout=30.0) as dl:
                    r = await dl.get(img_url)
                    r.raise_for_status()
                    img_bytes = r.content
                    ext = "png"
            except Exception:
                continue

        filename = f"{uuid.uuid4()}.{ext}"
        (GENERATED_DIR / filename).write_bytes(img_bytes)
        saved_urls.append(f"/api/images/{filename}")

    if not saved_urls:
        raise ValueError("Failed to save any generated images")

    return {
        "generated_image": True,
        "url": saved_urls[0],
        "urls": saved_urls,
        "text": text_response,
        "model": data.get("model", model),
    }


async def _read_image_to_base64(url: str, db=None) -> tuple[str, str] | None:
    """Read an image from a local path or external URL. Returns (mime_type, base64_data)."""
    if url.startswith("/api/images/"):
        filename = url.removeprefix("/api/images/").split("?")[0]
        # Sanitize
        if "/" in filename or "\\" in filename or ".." in filename:
            return None
        file_path = GENERATED_DIR / filename
        if not file_path.exists():
            return None
        data = file_path.read_bytes()
        ext = file_path.suffix.lower().lstrip(".")
        mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
        return mime_map.get(ext, "image/png"), base64.b64encode(data).decode()

    if url.startswith("/api/files/"):
        file_id_str = url.split("/api/files/")[1].split("?")[0]
        if db:
            try:
                from uuid import UUID
                from sqlalchemy import select
                from quip.models.file import File
                from quip.routers.files import UPLOAD_DIR
                file_uuid = UUID(file_id_str)
                result = await db.execute(select(File).where(File.id == file_uuid))
                file_record = result.scalar_one_or_none()
                if file_record:
                    file_path = UPLOAD_DIR / file_record.storage_path
                    if file_path.exists():
                        data = file_path.read_bytes()
                        mime = file_record.content_type or "image/png"
                        return mime, base64.b64encode(data).decode()
            except Exception:
                pass
        return None

    if url.startswith(("http://", "https://")):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    content_type = resp.headers.get("content-type", "image/png").split(";")[0].strip()
                    return content_type, base64.b64encode(resp.content).decode()
        except Exception:
            pass

    return None
