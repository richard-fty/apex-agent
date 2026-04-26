from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest

from tools.web import WebResearchTool, _plan_research_queries


@pytest.mark.asyncio
async def test_web_research_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        assert query == "nvda earnings"
        assert max_results == 4
        return [
            {"title": "Reuters", "url": "https://example.com/1", "snippet": "r1"},
            {"title": "SEC", "url": "https://example.com/2", "snippet": "r2"},
            {"title": "FT", "url": "https://example.com/3", "snippet": "r3"},
            {"title": "Bloomberg", "url": "https://example.com/4", "snippet": "r4"},
        ]

    async def fake_fetch(url: str, max_chars: int) -> str:
        return f"body:{url}:{max_chars}"

    monkeypatch.setattr("tools.web.search_web", fake_search)
    monkeypatch.setattr("tools.web._fetch_page_text", fake_fetch)

    tool = WebResearchTool()
    content = await tool.execute(query="nvda earnings", num_results=4, fetch_top=2, max_chars=1234)
    payload = json.loads(content)

    assert payload["query"] == "nvda earnings"
    assert len(payload["results"]) == 4
    assert payload["results"][0]["text"] == "body:https://example.com/1:1234"
    assert payload["results"][1]["text"] == "body:https://example.com/2:1234"
    assert "text" not in payload["results"][2]
    assert "text" not in payload["results"][3]


@pytest.mark.asyncio
async def test_web_research_marks_partial_fetch_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        return [
            {"title": "One", "url": "https://example.com/1", "snippet": "a"},
            {"title": "Two", "url": "https://example.com/2", "snippet": "b"},
        ]

    async def fake_fetch(url: str, max_chars: int) -> str:
        if url.endswith("/2"):
            raise httpx.TimeoutException("timed out")
        return "ok"

    monkeypatch.setattr("tools.web.search_web", fake_search)
    monkeypatch.setattr("tools.web._fetch_page_text", fake_fetch)

    tool = WebResearchTool()
    payload = json.loads(await tool.execute(query="nvda", fetch_top=2))

    assert payload["results"][0]["text"] == "ok"
    assert payload["results"][1]["fetch_error"] == "timeout"


@pytest.mark.asyncio
async def test_web_research_search_only_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"fetch": 0}

    async def fake_search(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        return [{"title": "Only", "url": "https://example.com/1", "snippet": "x"}]

    async def fake_fetch(url: str, max_chars: int) -> str:
        calls["fetch"] += 1
        return "unexpected"

    monkeypatch.setattr("tools.web.search_web", fake_search)
    monkeypatch.setattr("tools.web._fetch_page_text", fake_fetch)

    tool = WebResearchTool()
    payload = json.loads(await tool.execute(query="nvda", fetch_top=0))

    assert calls["fetch"] == 0
    assert "text" not in payload["results"][0]


@pytest.mark.asyncio
async def test_web_research_reuses_cached_fetches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"search": 0, "fetch": 0}

    async def fake_search(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        calls["search"] += 1
        return [{"title": "Only", "url": "https://example.com/1", "snippet": query}]

    async def fake_fetch(url: str, max_chars: int) -> str:
        calls["fetch"] += 1
        return "cached body"

    monkeypatch.setattr("tools.web.search_web", fake_search)
    monkeypatch.setattr("tools.web._fetch_page_text", fake_fetch)

    tool = WebResearchTool()
    first = json.loads(await tool.execute(query="nvda earnings", fetch_top=1))
    second = json.loads(await tool.execute(query="nvda filings", fetch_top=1))

    assert calls["search"] == 2
    assert calls["fetch"] == 1
    assert first["results"][0]["text"] == "cached body"
    assert second["results"][0]["text"] == "cached body"


def test_plan_research_queries_expands_vague_stock_query() -> None:
    queries = _plan_research_queries("Adobe ADBE stock analysis earnings financial performance 2026")
    month_year = datetime.now().strftime("%B %Y")
    year = str(datetime.now().year)
    assert len(queries) == 3
    assert queries[0] == f"Adobe ADBE latest news {month_year}"
    assert queries[1] == f"Adobe ADBE earnings guidance analyst reaction {year}"
    assert queries[2] == f"Adobe ADBE layoffs lawsuit acquisition product launch {year}"


def test_plan_research_queries_keeps_focused_company_news_query() -> None:
    queries = _plan_research_queries("Adobe layoffs latest news 2026")
    assert queries == ["Adobe layoffs latest news 2026"]


@pytest.mark.asyncio
async def test_web_research_uses_expanded_queries_for_vague_stock_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_queries: list[str] = []

    async def fake_search(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        seen_queries.append(query)
        slug = len(seen_queries)
        return [{"title": f"Result {slug}", "url": f"https://example.com/{slug}", "snippet": query}]

    monkeypatch.setattr("tools.web.search_web", fake_search)

    tool = WebResearchTool()
    month_year = datetime.now().strftime("%B %Y")
    year = str(datetime.now().year)
    payload = json.loads(await tool.execute(
        query="Adobe ADBE stock analysis earnings financial performance 2026",
        num_results=3,
        fetch_top=0,
    ))

    assert payload["queries_used"] == [
        f"Adobe ADBE latest news {month_year}",
        f"Adobe ADBE earnings guidance analyst reaction {year}",
        f"Adobe ADBE layoffs lawsuit acquisition product launch {year}",
    ]
    assert seen_queries == payload["queries_used"]
    assert len(payload["results"]) == 3
