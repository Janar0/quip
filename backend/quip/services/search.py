"""Web search providers — Tavily and SearXNG. Returns text results + images."""
import asyncio
import logging
import time
from dataclasses import dataclass

import httpx

from quip.services.config import get_setting

logger = logging.getLogger(__name__)

TIMEOUT = 10.0
MAX_IMAGES = 10

# Process-wide query cache. Repeated queries within a chat (clarifications,
# tool retries) skip the network round-trip. Keyed by (provider, query) —
# results are public web data so no per-user partitioning needed.
_SEARCH_CACHE_TTL = 1800  # 30 min — web pages don't change that fast
_SEARCH_CACHE_MAX = 128
_search_cache: dict[tuple[str, str, int], tuple[float, tuple]] = {}


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


async def web_search(
    query: str, max_results: int = 5
) -> tuple[list[SearchResult], list[ImageResult]]:
    """Dispatch to the configured search provider. Returns (text_results, image_results)."""
    from quip.services.skill_store import get_skill_setting
    provider = get_skill_setting("web_search", "provider", None) or get_setting("search_provider", "tavily")

    cache_key = (provider, query.strip(), max_results)
    cached = _search_cache_get(cache_key)
    if cached is not None:
        return cached

    if provider == "searxng":
        result = await _searxng_search(query, max_results)
    else:
        result = await _tavily_search(query, max_results)

    # Don't cache obvious failures — first item title "Error"/"Search error".
    if result[0] and result[0][0].title not in ("Error", "Search error"):
        _search_cache_put(cache_key, result)
    return result


async def _tavily_search(
    query: str, max_results: int
) -> tuple[list[SearchResult], list[ImageResult]]:
    """Search via Tavily API (https://api.tavily.com)."""
    from quip.services.skill_store import get_skill_setting
    api_key = get_skill_setting("web_search", "tavily_api_key", "") or get_setting("tavily_api_key", "")
    if not api_key:
        return (
            [SearchResult(title="Error", url="", snippet="Tavily API key not configured")],
            [],
        )

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
        for item in data.get("results", []):
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
                content=item.get("content", ""),
            ))

        # Tavily returns images as either a list of strings or list of {url, description}
        images: list[ImageResult] = []
        for item in data.get("images", []) or []:
            if isinstance(item, str):
                images.append(ImageResult(img_src=item, source_url=item))
            elif isinstance(item, dict):
                url = item.get("url") or ""
                if url:
                    images.append(
                        ImageResult(
                            img_src=url,
                            source_url=url,
                            title=item.get("description", "") or "",
                        )
                    )
        images = images[:MAX_IMAGES]

        return (
            results or [SearchResult(title="No results", url="", snippet=f"No results for: {query}")],
            images,
        )
    except Exception as e:
        logger.warning(f"Tavily search failed: {e}")
        return ([SearchResult(title="Search error", url="", snippet=str(e))], [])


async def _searxng_search(
    query: str, max_results: int
) -> tuple[list[SearchResult], list[ImageResult]]:
    """Search via a self-hosted SearXNG instance — runs text + image queries concurrently."""
    from quip.services.skill_store import get_skill_setting
    base_url = (get_skill_setting("web_search", "searxng_url", "") or get_setting("searxng_url", "")).rstrip("/")
    if not base_url:
        return (
            [SearchResult(title="Error", url="", snippet="SearXNG URL not configured")],
            [],
        )

    async def _fetch_text(client: httpx.AsyncClient) -> list[SearchResult]:
        resp = await client.get(
            f"{base_url}/search",
            params={"q": query, "format": "json", "pageno": 1},
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
            )
            for item in data.get("results", [])[:max_results]
        ]

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
        for item in data.get("results", []):
            img_src = item.get("img_src") or ""
            source_url = item.get("url") or ""
            title = item.get("title") or ""
            if img_src and source_url:
                images.append(ImageResult(img_src=img_src, source_url=source_url, title=title))
        return images[:MAX_IMAGES]

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            text_task = asyncio.create_task(_fetch_text(client))
            img_task = asyncio.create_task(_fetch_images(client))
            text_results, img_results = await asyncio.gather(
                text_task, img_task, return_exceptions=True
            )

        if isinstance(text_results, Exception):
            logger.warning(f"SearXNG text search failed: {text_results}")
            text_results = []
        if isinstance(img_results, Exception):
            logger.warning(f"SearXNG image search failed: {img_results}")
            img_results = []

        return (
            text_results or [SearchResult(title="No results", url="", snippet=f"No results for: {query}")],
            img_results,
        )
    except Exception as e:
        logger.warning(f"SearXNG search failed: {e}")
        return ([SearchResult(title="Search error", url="", snippet=str(e))], [])
