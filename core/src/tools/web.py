"""Built-in web research tool."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import Any

import httpx

from agent.core.models import ToolGroup, ToolParameter
from services.web_search import search_web
from tools.base import BuiltinTool


class WebResearchTool(BuiltinTool):
    name = "web_research"
    description = (
        "Search the web and fetch the top pages in one call. Returns each result's "
        "url, title, snippet, and fetched text when available. Prefer this over "
        "separate search and fetch calls."
    )
    tool_group = ToolGroup.RUNTIME
    is_read_only = True
    is_concurrency_safe = True
    requires_confirmation = False
    is_networked = True
    mutates_state = False
    parameters = [
        ToolParameter(name="query", type="string", description="Search query"),
        ToolParameter(
            name="num_results",
            type="integer",
            description="Number of search results to return (default: 5, max: 10)",
            required=False,
            default=5,
        ),
        ToolParameter(
            name="fetch_top",
            type="integer",
            description="How many of the top results to also fetch in a second network pass (default: 0, max: 5)",
            required=False,
            default=0,
        ),
        ToolParameter(
            name="max_chars",
            type="integer",
            description="Per-page character cap after fetch (default: 4000)",
            required=False,
            default=4000,
        ),
    ]

    def __init__(self) -> None:
        self._page_cache: dict[str, str] = {}

    async def execute(self, **kwargs: Any) -> str:
        query = kwargs["query"]
        raw_num_results = kwargs.get("num_results", 5)
        raw_fetch_top = kwargs.get("fetch_top", 0)
        raw_max_chars = kwargs.get("max_chars", 4000)
        num_results = max(1, min(int(5 if raw_num_results is None else raw_num_results), 10))
        fetch_top = max(0, min(int(0 if raw_fetch_top is None else raw_fetch_top), 5))
        max_chars = max(250, int(4000 if raw_max_chars is None else raw_max_chars))

        queries_used = _plan_research_queries(query)
        per_query_limit = max(2, min(num_results, 4))
        raw_results: list[dict[str, str]] = []
        for planned_query in queries_used:
            raw_results.extend(await search_web(planned_query, max_results=per_query_limit))
        deduped_results: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        for item in raw_results:
            url = (item.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            deduped_results.append({
                "title": (item.get("title") or url).strip(),
                "url": url,
                "snippet": (item.get("snippet") or "").strip(),
            })
            if len(deduped_results) >= num_results:
                break

        async def fetch_result(result: dict[str, str]) -> dict[str, Any]:
            enriched: dict[str, Any] = dict(result)
            url = result["url"]
            try:
                text = self._page_cache.get(url)
                if text is None:
                    text = await _fetch_page_text(url, max_chars)
                    self._page_cache[url] = text
                enriched["text"] = text[:max_chars]
            except httpx.TimeoutException:
                enriched["fetch_error"] = "timeout"
            except httpx.HTTPStatusError as exc:
                enriched["fetch_error"] = f"http_{exc.response.status_code}"
            except Exception as exc:  # pragma: no cover - defensive
                enriched["fetch_error"] = str(exc)
            return enriched

        fetched: list[dict[str, Any]] = []
        if fetch_top > 0 and deduped_results:
            fetched = await asyncio.gather(
                *(fetch_result(item) for item in deduped_results[:fetch_top])
            )

        enriched_results: list[dict[str, Any]] = fetched + [
            dict(item) for item in deduped_results[len(fetched):]
        ]
        payload = {
            "query": query,
            "queries_used": queries_used,
            "results": enriched_results,
        }
        return json.dumps(payload, indent=2)


_FOCUSED_COMPANY_NEWS_HINTS = {
    "earnings",
    "guidance",
    "analyst",
    "downgrade",
    "upgrade",
    "layoff",
    "layoffs",
    "lawsuit",
    "acquisition",
    "merger",
    "regulation",
    "regulatory",
    "sec",
    "filing",
    "product",
    "launch",
    "latest",
    "news",
    "outlook",
    "demand",
    "strategy",
}

_GENERIC_STOCK_QUERY_MARKERS = {
    "stock",
    "analysis",
    "financial",
    "performance",
    "recent",
    "information",
    "share",
    "price",
}


def _plan_research_queries(query: str) -> list[str]:
    cleaned = _normalize_query(query)
    if not _should_expand_stock_query(cleaned):
        return [cleaned]

    subject = _extract_company_subject(cleaned)
    year = str(datetime.now().year)
    month_year = datetime.now().strftime("%B %Y")
    return [
        f"{subject} latest news {month_year}",
        f"{subject} earnings guidance analyst reaction {year}",
        f"{subject} layoffs lawsuit acquisition product launch {year}",
    ]


def _should_expand_stock_query(query: str) -> bool:
    lowered = query.lower()
    tokens = set(re.findall(r"[a-z0-9-]+", lowered))
    if not tokens:
        return False
    generic_hits = tokens.intersection(_GENERIC_STOCK_QUERY_MARKERS)
    if not generic_hits:
        return False
    if "stock analysis" in lowered or "financial performance" in lowered or "recent information" in lowered:
        return True
    focused_hits = tokens.intersection(_FOCUSED_COMPANY_NEWS_HINTS) - {"news"}
    return len(focused_hits) <= 1


def _extract_company_subject(query: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9&.-]+", query)
    subject_tokens: list[str] = []
    for token in tokens:
        if token.lower() in _GENERIC_STOCK_QUERY_MARKERS:
            break
        subject_tokens.append(token)
    if not subject_tokens:
        subject_tokens = tokens[:3]
    return " ".join(subject_tokens).strip() or query.strip()


def _normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query).strip()


def _strip_html(html: str) -> str:
    """Simple HTML tag stripping. Not perfect but good enough for agent consumption."""
    import re
    # Remove script and style blocks
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove tags
    html = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace
    html = re.sub(r"\s+", " ", html).strip()
    return html


async def _fetch_page_text(url: str, max_chars: int) -> str:
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
        resp = await client.get(url, headers={"User-Agent": "ApexAgent/0.1"})
        resp.raise_for_status()

    content_type = resp.headers.get("content-type", "")
    text = resp.text

    if "html" in content_type:
        text = _strip_html(text)

    if len(text) > max_chars:
        return text[:max_chars] + f"\n\n[... truncated, {len(resp.text)} total chars]"
    return text
