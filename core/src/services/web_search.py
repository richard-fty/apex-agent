"""Web search providers for runtime research and web tools."""

from __future__ import annotations

import logging
import os
import re
from urllib.parse import quote

import httpx

from config import settings

logger = logging.getLogger(__name__)


async def search_web(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
    """Search the web using Tavily when configured, else fall back to DuckDuckGo.

    When a Tavily API key is configured, keep Tavily as the active provider and
    do not silently swap search engines on an empty/error result.
    """
    if _tavily_api_key():
        return await _search_tavily(query, max_results=max_results)
    return await _search_duckduckgo(query, max_results=max_results)


def _tavily_api_key() -> str:
    return os.environ.get("TAVILY_API_KEY", "").strip() or settings.tavily_api_key.strip()


async def _search_tavily(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                    "topic": "general",
                    "include_answer": False,
                    "include_raw_content": False,
                },
                headers={
                    "Authorization": f"Bearer {_tavily_api_key()}",
                    "Content-Type": "application/json",
                    "User-Agent": "ApexAgent/0.1",
                },
            )
            resp.raise_for_status()
    except Exception as exc:
        logger.warning("Tavily search failed for query %r: %s", query, exc)
        return []

    data = resp.json()
    results: list[dict[str, str]] = []
    for item in data.get("results", [])[:max_results]:
        url = (item.get("url") or "").strip()
        title = (item.get("title") or url).strip()
        snippet = (item.get("content") or "").strip()
        if not url:
            continue
        results.append({"title": title, "url": url, "snippet": snippet})
    return results


async def _search_duckduckgo(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
    url = f"https://duckduckgo.com/html/?q={quote(query)}"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "ApexAgent/0.1"})
            resp.raise_for_status()
    except Exception:
        return []

    html = resp.text
    pattern = re.compile(
        r'<a[^>]*class="result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    results: list[dict[str, str]] = []
    for match in pattern.finditer(html):
        title = re.sub(r"<[^>]+>", "", match.group("title")).strip()
        href = match.group("url").strip()
        if not title or not href:
            continue
        if href.startswith("//"):
            href = "https:" + href
        results.append({"title": title, "url": href, "snippet": ""})
        if len(results) >= max_results:
            break
    return results
