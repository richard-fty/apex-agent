from __future__ import annotations

from agent.runtime.tool_dispatch import ToolDispatch
from agent.skills.loader import SkillLoader


def test_preload_by_intent_falls_back_for_obvious_stock_request() -> None:
    loader = SkillLoader(ToolDispatch())
    loader.discover()

    loaded = loader.pre_load_by_intent("analyze adobe stock and give me a briefing")

    assert "stock_strategy" in loaded


def test_load_skill_for_tool_recovers_unloaded_skill_tool() -> None:
    loader = SkillLoader(ToolDispatch())
    loader.discover()
    assert loader.load_skill("stock_strategy") is True
    assert loader.unload_skill("stock_strategy") is True

    loaded_name = loader.load_skill_for_tool("fetch_market_data")

    assert loaded_name == "stock_strategy"
    assert "stock_strategy" in loader.loaded
