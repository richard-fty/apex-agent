"""Web search providers for runtime research and web tools."""

from __future__ import annotations

import re
from urllib.parse import quote

import httpx

from config import settings


async def search_web(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
    """Search the web using Tavily when configured, else fall back to DuckDuckGo."""
    if settings.tavily_api_key:
        results = await _search_tavily(query, max_results=max_results)
        if results:
            return results
    return await _search_duckduckgo(query, max_results=max_results)


async def _search_tavily(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.tavily_api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                    "include_answer": False,
                    "include_raw_content": False,
                },
                headers={"Content-Type": "application/json", "User-Agent": "Relay/0.1"},
            )
            resp.raise_for_status()
    except Exception:
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
            resp = await client.get(url, headers={"User-Agent": "Relay/0.1"})
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
