from __future__ import annotations

import os
import httpx
import pytest

from config import settings
from services import web_search


@pytest.mark.asyncio
async def test_search_web_does_not_fallback_when_tavily_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_key = settings.tavily_api_key
    settings.tavily_api_key = "tvly-test"

    async def fake_tavily(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        assert query == "nvda earnings"
        assert max_results == 3
        return []

    async def fake_ddg(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        raise AssertionError("DuckDuckGo fallback should not run when Tavily is configured")

    monkeypatch.setattr(web_search, "_search_tavily", fake_tavily)
    monkeypatch.setattr(web_search, "_search_duckduckgo", fake_ddg)

    try:
        results = await web_search.search_web("nvda earnings", max_results=3)
    finally:
        settings.tavily_api_key = original_key

    assert results == []


@pytest.mark.asyncio
async def test_search_web_uses_live_env_tavily_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_key = settings.tavily_api_key
    settings.tavily_api_key = ""
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-live-env")

    async def fake_tavily(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        assert os.environ["TAVILY_API_KEY"] == "tvly-live-env"
        return [{"title": "Env", "url": "https://example.com/env", "snippet": "ok"}]

    async def fake_ddg(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        raise AssertionError("DuckDuckGo fallback should not run when live env key exists")

    monkeypatch.setattr(web_search, "_search_tavily", fake_tavily)
    monkeypatch.setattr(web_search, "_search_duckduckgo", fake_ddg)

    try:
        results = await web_search.search_web("nvda")
    finally:
        settings.tavily_api_key = original_key

    assert results == [{"title": "Env", "url": "https://example.com/env", "snippet": "ok"}]


@pytest.mark.asyncio
async def test_search_tavily_uses_bearer_auth_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_key = settings.tavily_api_key
    settings.tavily_api_key = "tvly-secret"
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-secret")
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "results": [
                    {
                        "title": "Reuters",
                        "url": "https://example.com/reuters",
                        "content": "snippet",
                    }
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, url: str, *, json: dict[str, object], headers: dict[str, str]) -> FakeResponse:
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    try:
        results = await web_search._search_tavily("nvda", max_results=2)
    finally:
        settings.tavily_api_key = original_key

    assert results == [
        {
            "title": "Reuters",
            "url": "https://example.com/reuters",
            "snippet": "snippet",
        }
    ]
    assert captured["url"] == "https://api.tavily.com/search"
    assert captured["headers"] == {
        "Authorization": "Bearer tvly-secret",
        "Content-Type": "application/json",
        "User-Agent": "ApexAgent/0.1",
    }
    assert captured["json"] == {
        "query": "nvda",
        "max_results": 2,
        "search_depth": "basic",
        "topic": "general",
        "include_answer": False,
        "include_raw_content": False,
    }
