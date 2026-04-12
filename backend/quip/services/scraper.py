"""Web page content extraction — Jina Reader with direct-fetch fallback."""
import logging
import re

import httpx

logger = logging.getLogger(__name__)

JINA_TIMEOUT = 15.0
DIRECT_TIMEOUT = 10.0
DEFAULT_MAX_CHARS = 15000


async def read_url(url: str, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Fetch URL content as markdown. Tries Jina Reader first, then direct fetch."""
    try:
        return await _jina_reader(url, max_chars)
    except Exception as e:
        logger.info(f"Jina Reader failed for {url}: {e}, trying direct fetch")
        try:
            return await _direct_fetch(url, max_chars)
        except Exception as e2:
            logger.warning(f"Direct fetch also failed for {url}: {e2}")
            return f"Failed to read {url}: {e2}"


async def _jina_reader(url: str, max_chars: int) -> str:
    """Use Jina Reader API to get clean markdown from any URL."""
    async with httpx.AsyncClient(timeout=JINA_TIMEOUT) as client:
        resp = await client.get(
            f"https://r.jina.ai/{url}",
            headers={
                "Accept": "text/markdown",
                "X-No-Cache": "true",
            },
        )
        resp.raise_for_status()
        text = resp.text.strip()

    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n... (truncated)"
    return text


async def _direct_fetch(url: str, max_chars: int) -> str:
    """Fallback: fetch HTML and strip tags."""
    async with httpx.AsyncClient(timeout=DIRECT_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; QUIP/1.0; +https://quip.dev)",
        })
        resp.raise_for_status()
        html = resp.text

    # Strip script/style blocks, then all tags
    text = re.sub(r'<(script|style|noscript)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n... (truncated)"
    return text
