"""Mock benchmark mode — run eval suite without real LLM API calls.

This module provides a mock implementation of the benchmark runner that:
- Uses FakeBrain with deterministic responses instead of real LLM APIs
- Returns predictable tool results based on test case expectations
- Allows CI to run the full benchmark matrix without API costs
- Verifies the eval pipeline (scoring, reporting, baselines) works correctly

Usage:
    APEX_MOCK_LLM=1 uv run python -m eval.runner --scenario core_agent
    uv run python -m eval.runner --scenario core_agent --mock
"""

from __future__ import annotations

import json
import os
from typing import Any
from types import SimpleNamespace

from agent.runtime.managed_runtime import LiteLLMBrain


class MockBrain(LiteLLMBrain):
    """Mock LLM brain that returns deterministic responses for benchmarking.
    
    This replaces real LLM calls with predictable responses based on the test case.
    The responses are designed to exercise the agent loop and tool calling logic
    without requiring actual API calls.
    """
    
    def __init__(self, test_case: dict[str, Any]) -> None:
        self.test_case = test_case
        self._call_count = 0
        self._expected_tools = test_case.get("expected_tools", [])
        self._must_contain = test_case.get("must_contain", [])
        self._step = 0
    
    async def complete(self, *, model, messages, tools, stream) -> Any:
        """Return deterministic mock response based on conversation state."""
        self._call_count += 1
        self._step += 1
        
        # Determine what phase we're in
        user_messages = [m for m in messages if m.get("role") == "user"]
        assistant_messages = [m for m in messages if m.get("role") == "assistant"]
        tool_messages = [m for m in messages if m.get("role") == "tool"]
        
        max_steps = self.test_case.get("max_steps", 20)
        
        # If we've made progress and have tool results, summarize and finish
        if len(tool_messages) >= len(self._expected_tools) and self._expected_tools:
            return self._stream_final_answer()
        
        # If we haven't made all expected tool calls yet, make the next one
        if len(tool_messages) < len(self._expected_tools):
            tool_idx = len(tool_messages)
            tool_name = self._expected_tools[tool_idx] if tool_idx < len(self._expected_tools) else "read_file"
            return self._stream_tool_call(tool_name, tool_idx)
        
        # Default: provide final answer
        return self._stream_final_answer()
    
    def _stream_tool_call(self, tool_name: str, index: int) -> "MockStream":
        """Create a stream that yields a tool call."""
        arguments = self._tool_arguments(tool_name)
        chunk = SimpleNamespace(
            choices=[SimpleNamespace(
                delta=SimpleNamespace(
                    content=None,
                    tool_calls=[SimpleNamespace(
                        id=f"call_{index}",
                        index=0,
                        function=SimpleNamespace(
                            name=tool_name,
                            arguments=json.dumps(arguments)
                        )
                    )]
                )
            )],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10, total_tokens=20)
        )
        return MockStream([chunk])

    def _tool_arguments(self, tool_name: str) -> dict[str, Any]:
        if self.test_case.get("id") == "lt1_brief_nvda":
            if tool_name == "web_research":
                return {
                    "query": "NVDA earnings filings analyst news",
                    "num_results": 5,
                    "fetch_top": 3,
                    "max_chars": 4000,
                }
            if tool_name == "fetch_market_data":
                return {"symbol": "NVDA", "period": "6mo", "interval": "1d"}
            if tool_name == "compute_indicator":
                return {"symbol": "NVDA", "indicator": "RSI", "period": "6mo", "window": 14}
            if tool_name == "generate_chart":
                return {
                    "symbol": "NVDA",
                    "period": "6mo",
                    "indicators": "sma_50,sma_200,volume,rsi",
                    "chart_type": "candle",
                }
            if tool_name == "write_file":
                return {
                    "path": "results/lt1_briefing/render.py",
                    "content": (
                        "from pathlib import Path\n"
                        "Path('results/lt1_briefing').mkdir(parents=True, exist_ok=True)\n"
                        "print('render placeholder')\n"
                    ),
                }
            if tool_name == "run_command":
                return {"command": "python3 results/lt1_briefing/render.py", "timeout": 30}

        if tool_name == "read_file":
            return {"path": "tests/fixtures/core_agent/mission.txt"}
        return {}
    
    def _stream_final_answer(self) -> "MockStream":
        """Create a stream that yields the final answer."""
        # Include must_contain items in the answer
        answer_parts = []
        if self._must_contain:
            for item in self._must_contain:
                answer_parts.append(f"The answer includes: {item}")
        else:
            answer_parts.append("Task completed successfully.")
        
        content = " ".join(answer_parts)
        
        chunk = SimpleNamespace(
            choices=[SimpleNamespace(
                delta=SimpleNamespace(
                    content=content,
                    tool_calls=None
                )
            )],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10, total_tokens=20)
        )
        return MockStream([chunk])


class MockStream:
    """Async iterator that yields mock chunks."""
    
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks
        self._index = 0
    
    def __aiter__(self) -> "MockStream":
        return self
    
    async def __anext__(self) -> Any:
        if self._index >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._index]
        self._index += 1
        return chunk


def is_mock_mode() -> bool:
    """Check if mock mode is enabled via environment variable or flag."""
    return os.environ.get("APEX_MOCK_LLM", "").lower() in ("1", "true", "yes")


def create_mock_brain(test_case: dict[str, Any]) -> MockBrain:
    """Factory function to create a mock brain for a test case."""
    return MockBrain(test_case)


# Mock tool responses for predictable benchmark behavior
MOCK_TOOL_RESPONSES: dict[str, str] = {
    "read_file": "Project codename: Northstar. Launch date: 2026-09-01. Team size: 5.",
    "write_file": "File written successfully.",
    "edit_file": "File edited successfully.",
    "list_dir": "- mission.txt\n- notes.txt\n- summary.txt",
    "run_command": "Command executed successfully.",
    "web_search": "Search results: Northstar project is a next-generation AI agent platform.",
    "web_fetch": "Fetched content about AI agent architectures.",
    "web_research": json.dumps({
        "query": "NVDA earnings filings analyst news",
        "results": [
            {"title": "NVIDIA quarterly results", "url": "https://example.com/nvda/earnings", "snippet": "Revenue and margin update", "text": "Latest quarterly results and outlook."},
            {"title": "NVIDIA SEC filing", "url": "https://example.com/nvda/filing", "snippet": "10-Q filing", "text": "Recent filing with risk disclosures."},
            {"title": "Reuters on NVIDIA", "url": "https://example.com/nvda/reuters", "snippet": "Analyst and market reaction", "text": "Market reaction to the latest print."},
            {"title": "FT on AI spending", "url": "https://example.com/nvda/ft", "snippet": "Datacenter demand context"},
            {"title": "Bloomberg on semis", "url": "https://example.com/nvda/bloomberg", "snippet": "Sector positioning"}
        ]
    }, indent=2),
    "rag_query": "Retrieved: The Northstar project uses a managed-agent architecture.",
    "rag_list_collections": "Collections: documents, code, research",
    "rag_index": "Documents indexed successfully.",
    "forget": "Memory cleared.",
    "recall_session": "Previous sessions: test_001, test_002",
    "remember": "Information stored.",
    "todo_view": "Current tasks:\n1. Read mission file\n2. Summarize findings",
    "todo_write": "Todo list created.",
    "todo_update": "Todo updated.",
    "list_skills": "Available skills: stock_strategy, research_and_report",
    "load_skill": "Skill loaded.",
    "unload_skill": "Skill unloaded.",
    "read_skill_reference": "Reference: Use quantitative analysis for stock evaluation.",
}


def get_mock_tool_response(tool_name: str, arguments: dict[str, Any]) -> str:
    """Get a deterministic mock response for a tool call."""
    # Try exact match first
    if tool_name in MOCK_TOOL_RESPONSES:
        return MOCK_TOOL_RESPONSES[tool_name]
    
    # Default response for unknown tools
    return f"Mock response for {tool_name}"


def inject_mock_brain(runtime: Any, test_case: dict[str, Any]) -> None:
    """Inject a mock brain into a runtime for testing.
    
    This patches the runtime's brain with a MockBrain that returns
    deterministic responses based on the test case.
    """
    mock_brain = create_mock_brain(test_case)
    runtime.brain = mock_brain
