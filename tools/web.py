"""Built-in web tools: web_search (stub) and web_fetch."""

from __future__ import annotations

import re
from typing import Any

import httpx

from agent.core.models import ToolGroup, ToolParameter
from services.web_search import search_web
from tools.base import BuiltinTool


class WebSearchTool(BuiltinTool):
    name = "web_search"
    description = (
        "Search the web for information. Returns search results with titles, URLs, and snippets."
    )
    tool_group = ToolGroup.RUNTIME
    is_read_only = True
    is_concurrency_safe = True
    requires_confirmation = True
    is_networked = True
    mutates_state = False
    parameters = [
        ToolParameter(name="query", type="string", description="Search query"),
        ToolParameter(
            name="num_results",
            type="integer",
            description="Number of results to return (default: 5)",
            required=False,
            default=5,
        ),
    ]

    async def execute(self, **kwargs: Any) -> str:
        query = kwargs["query"]
        num_results = int(kwargs.get("num_results", 5) or 5)
        results = await search_web(query, max_results=max(1, min(num_results, 10)))
        if not results:
            return f"No web results found for: {query}"

        lines = [f"Web search results for: {query}", ""]
        for index, result in enumerate(results, start=1):
            lines.append(f"{index}. {result['title']}")
            lines.append(f"   URL: {result['url']}")
            snippet = result.get("snippet", "").strip()
            if snippet:
                lines.append(f"   Snippet: {snippet}")
            lines.append("")
        return "\n".join(lines).strip()


class WebFetchTool(BuiltinTool):
    name = "web_fetch"
    description = "Fetch the content of a web page and return it as text. Strips HTML tags for readability."
    tool_group = ToolGroup.RUNTIME
    is_read_only = True
    is_concurrency_safe = True
    requires_confirmation = True
    is_networked = True
    mutates_state = False
    parameters = [
        ToolParameter(name="url", type="string", description="URL to fetch"),
        ToolParameter(
            name="max_chars",
            type="integer",
            description="Max characters to return (default: 5000)",
            required=False,
            default=5000,
        ),
    ]

    async def execute(self, **kwargs: Any) -> str:
        url = kwargs["url"]
        max_chars = kwargs.get("max_chars", 5000)

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
                resp = await client.get(url, headers={"User-Agent": "ApexAgent/0.1"})
                resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            text = resp.text

            # Basic HTML tag stripping
            if "html" in content_type:
                text = _strip_html(text)

            if len(text) > max_chars:
                text = text[:max_chars] + f"\n\n[... truncated, {len(resp.text)} total chars]"

            return text

        except httpx.TimeoutException:
            return f"Error: Request timed out fetching {url}"
        except httpx.HTTPStatusError as e:
            return f"Error: HTTP {e.response.status_code} fetching {url}"
        except Exception as e:
            return f"Error fetching {url}: {e}"


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
