"""Web search providers — Tavily and SearXNG. Returns text results + images."""
import asyncio
import logging
import time
from dataclasses import dataclass

import httpx

from quip.core.config import get_setting

logger = logging.getLogger(__name__)

TIMEOUT = 10.0
MAX_IMAGES = 10

# Process-wide query cache. Repeated queries within a chat (clarifications,
# tool retries) skip the network round-trip. Keyed by (provider, query) —
# results are public web data so no per-user partitioning needed.
_SEARCH_CACHE_TTL = 1800  # 30 min — web pages don't change that fast
_SEARCH_CACHE_MAX = 128
_search_cache: dict[tuple[str, str, int], tuple[float, "SearchResponse"]] = {}


def _search_cache_get(key):
    hit = _search_cache.get(key)
    if not hit:
        return None
    ts, val = hit
    if time.time() - ts > _SEARCH_CACHE_TTL:
        _search_cache.pop(key, None)
        return None
    return val


def _search_cache_put(key, val):
    if len(_search_cache) >= _SEARCH_CACHE_MAX:
        for k, _ in sorted(_search_cache.items(), key=lambda kv: kv[1][0])[: _SEARCH_CACHE_MAX // 4]:
            _search_cache.pop(k, None)
    _search_cache[key] = (time.time(), val)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    content: str = ""


@dataclass
class ImageResult:
    img_src: str
    source_url: str
    title: str = ""


@dataclass
class SearchResponse:
    """Search output with explicit retrieval state for the model and UI."""

    results: list[SearchResult]
    images: list[ImageResult]
    error: str | None = None
    warning: str | None = None

    @property
    def status(self) -> str:
        if self.error:
            return "error"
        if not self.results:
            return "no_results"
        if self.warning:
            return "partial"
        return "success"


def _is_http_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = httpx.URL(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.host)
    except Exception:
        return False


async def web_search(
    query: str, max_results: int = 5
) -> SearchResponse:
    """Dispatch to the configured search provider with explicit outcome metadata."""
    from quip.services.skill_store import get_skill_setting
    provider = str(
        get_skill_setting("web_search", "provider", None)
        or get_setting("search_provider", "searxng")
    ).strip().lower()

    cache_key = (provider, query.strip(), max_results)
    cached = _search_cache_get(cache_key)
    if cached is not None:
        return cached

    if provider == "searxng":
        result = await _searxng_search(query, max_results)
    elif provider == "tavily":
        result = await _tavily_search(query, max_results)
    else:
        logger.warning("Unsupported web search provider configured: %s", provider)
        result = SearchResponse([], [], error="Web search provider is not configured correctly.")

    # Don't cache unavailable or degraded responses so a later retry can recover.
    if not result.error and not result.warning:
        _search_cache_put(cache_key, result)
    return result


async def _tavily_search(
    query: str, max_results: int
) -> SearchResponse:
    """Search via Tavily API (https://api.tavily.com)."""
    from quip.services.skill_store import get_skill_setting
    api_key = get_skill_setting("web_search", "tavily_api_key", "") or get_setting("tavily_api_key", "")
    if not api_key:
        return SearchResponse([], [], error="Tavily API key is not configured.")

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "query": query,
                    "max_results": max_results,
                    "include_answer": False,
                    "include_raw_content": False,
                    "include_images": True,
                    "include_image_descriptions": True,
                    "api_key": api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("results", []) or []:
            if not isinstance(item, dict) or not _is_http_url(item.get("url")):
                continue
            url = item["url"]
            results.append(SearchResult(
                title=item.get("title", "") or url,
                url=url,
                snippet=item.get("content", ""),
                content=item.get("content", ""),
            ))

        # Tavily returns images as either a list of strings or list of {url, description}
        images: list[ImageResult] = []
        for item in data.get("images", []) or []:
            if isinstance(item, str):
                if _is_http_url(item):
                    images.append(ImageResult(img_src=item, source_url=item))
            elif isinstance(item, dict):
                url = item.get("url") or ""
                if _is_http_url(url):
                    images.append(
                        ImageResult(
                            img_src=url,
                            source_url=item.get("source_url") if _is_http_url(item.get("source_url")) else url,
                            title=item.get("description", "") or "",
                        )
                    )
        images = images[:MAX_IMAGES]

        return SearchResponse(results, images)
    except Exception as e:
        logger.warning("Tavily search failed (%s)", type(e).__name__)
        return SearchResponse(
            [], [], error=f"Tavily search is unavailable ({type(e).__name__})."
        )


async def _searxng_search(
    query: str, max_results: int
) -> SearchResponse:
    """Search via a self-hosted SearXNG instance — runs text + image queries concurrently."""
    from quip.services.skill_store import get_skill_setting
    base_url = (
        get_skill_setting("web_search", "searxng_url", "")
        or get_setting("searxng_url", "http://127.0.0.1:8888")
    ).rstrip("/")
    if not base_url:
        return SearchResponse([], [], error="SearXNG URL is not configured.")

    async def _fetch_text(client: httpx.AsyncClient) -> list[SearchResult]:
        resp = await client.get(
            f"{base_url}/search",
            params={"q": query, "format": "json", "pageno": 1},
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in (data.get("results", []) or [])[:max_results]:
            if not isinstance(item, dict) or not _is_http_url(item.get("url")):
                continue
            url = item["url"]
            results.append(SearchResult(
                title=item.get("title", "") or url,
                url=url,
                snippet=item.get("content", ""),
            ))
        return results

    async def _fetch_images(client: httpx.AsyncClient) -> list[ImageResult]:
        resp = await client.get(
            f"{base_url}/search",
            params={
                "q": query,
                "format": "json",
                "categories": "images",
                "engines": "bing images,google images",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        images: list[ImageResult] = []
        for item in data.get("results", []) or []:
            if not isinstance(item, dict):
                continue
            img_src = item.get("img_src") or ""
            source_url = item.get("url") or ""
            title = item.get("title") or ""
            if _is_http_url(img_src) and _is_http_url(source_url):
                images.append(ImageResult(img_src=img_src, source_url=source_url, title=title))
        return images[:MAX_IMAGES]

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            text_task = asyncio.create_task(_fetch_text(client))
            img_task = asyncio.create_task(_fetch_images(client))
            text_results, img_results = await asyncio.gather(
                text_task, img_task, return_exceptions=True
            )

        error = None
        warning = None
        if isinstance(text_results, Exception):
            logger.warning("SearXNG text search failed (%s)", type(text_results).__name__)
            error = f"SearXNG text search is unavailable ({type(text_results).__name__})."
            text_results = []
        if isinstance(img_results, Exception):
            logger.warning("SearXNG image search failed (%s)", type(img_results).__name__)
            warning = f"SearXNG image search is unavailable ({type(img_results).__name__})."
            img_results = []

        return SearchResponse(
            text_results,
            img_results,
            error=error,
            warning=warning,
        )
    except Exception as e:
        logger.warning("SearXNG search failed (%s)", type(e).__name__)
        return SearchResponse(
            [], [], error=f"SearXNG search is unavailable ({type(e).__name__})."
        )
