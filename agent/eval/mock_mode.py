"""Mock mode — replace tools with deterministic test doubles.

Used for:
  - Benchmarking: same inputs every time, no network variability
  - Testing: verify agent behavior without real API calls
  - Cost savings: no LLM/API costs for tool execution
  - Failure injection: test how agent handles errors
"""

from __future__ import annotations

import json
from typing import Any, Callable, Awaitable

from agent.core.models import ToolDef
from agent.runtime.tool_dispatch import ToolDispatch


# Type for mock handlers
MockHandler = Callable[..., Awaitable[str] | str]


class MockToolRegistry:
    """Registry of mock tool responses."""

    def __init__(self) -> None:
        self._mocks: dict[str, MockHandler] = {}
        self._static_responses: dict[str, str] = {}
        self._failure_tools: dict[str, str] = {}  # tool → error message

    def mock_static(self, tool_name: str, response: str) -> None:
        """Set a static response for a tool."""
        self._static_responses[tool_name] = response

    def mock_handler(self, tool_name: str, handler: MockHandler) -> None:
        """Set a custom mock handler for a tool."""
        self._mocks[tool_name] = handler

    def mock_failure(self, tool_name: str, error: str) -> None:
        """Make a tool always fail with a specific error."""
        self._failure_tools[tool_name] = error

    def get_handler(self, tool_name: str) -> MockHandler | None:
        """Get the mock handler for a tool, if one exists."""
        # Check failure injection first
        if tool_name in self._failure_tools:
            error_msg = self._failure_tools[tool_name]
            async def fail_handler(**kwargs: Any) -> str:
                return json.dumps({"error": error_msg})
            return fail_handler

        # Check custom handler
        if tool_name in self._mocks:
            return self._mocks[tool_name]

        # Check static response
        if tool_name in self._static_responses:
            response = self._static_responses[tool_name]
            async def static_handler(**kwargs: Any) -> str:
                return response
            return static_handler

        return None

    def has_mock(self, tool_name: str) -> bool:
        return (
            tool_name in self._mocks
            or tool_name in self._static_responses
            or tool_name in self._failure_tools
        )


def apply_mocks(dispatch: ToolDispatch, mock_registry: MockToolRegistry) -> list[str]:
    """Replace real tool handlers with mocks in the dispatch.

    Returns list of tool names that were mocked.
    """
    mocked = []
    for name in dispatch.tool_names:
        handler = mock_registry.get_handler(name)
        if handler is not None:
            # Re-register with mock handler, keeping the same ToolDef
            tool_def = dispatch._tools.get(name)
            if tool_def:
                dispatch._handlers[name] = handler
                mocked.append(name)
    return mocked


# ── Preset mocks for stock_strategy ───────────────────────────────────

def get_stock_strategy_mocks() -> MockToolRegistry:
    """Get deterministic mocks for the stock_strategy skill."""
    registry = MockToolRegistry()

    # Mock fetch_market_data with realistic static data
    registry.mock_static("fetch_market_data", json.dumps({
        "symbol": "MOCK",
        "period": "6mo",
        "interval": "1d",
        "data_points": 126,
        "date_range": "2024-09-25 to 2025-03-25",
        "latest": {
            "date": "2025-03-25",
            "open": 195.20,
            "high": 198.50,
            "low": 194.80,
            "close": 197.30,
            "volume": 45000000,
        },
        "stats": {
            "period_high": 215.40,
            "period_low": 178.60,
            "avg_volume": 52000000,
            "price_change_pct": 8.45,
        },
        "recent_data": [
            {"date": "2025-03-21", "open": 192.10, "high": 194.50, "low": 191.80, "close": 193.90, "volume": 48000000},
            {"date": "2025-03-24", "open": 194.00, "high": 196.20, "low": 193.50, "close": 195.20, "volume": 43000000},
            {"date": "2025-03-25", "open": 195.20, "high": 198.50, "low": 194.80, "close": 197.30, "volume": 45000000},
        ],
    }, indent=2))

    # Mock compute_indicator
    registry.mock_static("compute_indicator", json.dumps({
        "symbol": "MOCK",
        "indicator": "RSI",
        "params": {"window": 14},
        "latest_value": 34.2,
        "signal": "oversold (potential buy)",
    }, indent=2))

    # Mock generate_chart
    registry.mock_static("generate_chart", json.dumps({
        "chart_saved": "charts/MOCK_6mo.png",
        "symbol": "MOCK",
        "period": "6mo",
        "indicators": ["sma_20", "sma_50", "volume"],
        "terminal_preview": "(mock chart)",
    }, indent=2))

    # Mock run_backtest
    registry.mock_static("run_backtest", json.dumps({
        "symbol": "MOCK",
        "period": "1y",
        "initial_capital": 10000,
        "final_value": 11420.50,
        "total_return_pct": 14.21,
        "buy_and_hold_return_pct": 8.45,
        "alpha_pct": 5.76,
        "sharpe_ratio": 1.42,
        "max_drawdown_pct": -8.30,
        "total_trades": 12,
        "win_rate_pct": 66.7,
    }, indent=2))

    # Mock write_strategy
    registry.mock_static("write_strategy", json.dumps({
        "saved": "strategies/mock_strategy.md",
        "name": "Mock Strategy",
        "size_bytes": 512,
    }))

    # Mock compare_strategies
    registry.mock_static("compare_strategies", json.dumps({
        "strategies_found": 1,
        "strategies": [{"name": "mock_strategy", "file": "strategies/mock_strategy.md"}],
    }))

    return registry
