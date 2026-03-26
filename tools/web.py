"""Built-in web tools: web_search (stub) and web_fetch."""

from __future__ import annotations

from typing import Any

import httpx

from agent.models import ToolParameter
from tools.base import BuiltinTool


class WebSearchTool(BuiltinTool):
    name = "web_search"
    description = (
        "Search the web for information. Returns search results with titles and snippets. "
        "Note: This is a stub — replace with a real search API (SerpAPI, Brave, etc.) for production."
    )
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
        return (
            f"Web search for: '{query}'\n\n"
            "Note: web_search is currently a stub. To enable real search, "
            "configure a search API (SerpAPI, Brave Search, etc.) in config.py.\n\n"
            "For now, use web_fetch to read specific URLs directly."
        )


class WebFetchTool(BuiltinTool):
    name = "web_fetch"
    description = "Fetch the content of a web page and return it as text. Strips HTML tags for readability."
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
                resp = await client.get(url, headers={"User-Agent": "AgentHarness/0.1"})
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
