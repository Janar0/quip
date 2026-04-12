"""Web search providers — Tavily and SearXNG. Returns text results + images."""
import asyncio
import logging
from dataclasses import dataclass

import httpx

from quip.services.config import get_setting

logger = logging.getLogger(__name__)

TIMEOUT = 10.0
MAX_IMAGES = 10


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
    provider = get_setting("search_provider", "tavily")
    if provider == "searxng":
        return await _searxng_search(query, max_results)
    return await _tavily_search(query, max_results)


async def _tavily_search(
    query: str, max_results: int
) -> tuple[list[SearchResult], list[ImageResult]]:
    """Search via Tavily API (https://api.tavily.com)."""
    api_key = get_setting("tavily_api_key", "")
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
    base_url = get_setting("searxng_url", "").rstrip("/")
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
