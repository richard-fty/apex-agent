"""T1.7 contract — Universal Hands parity across all tool backends.

Gap #2 from doc/gaps-review-2026-04-18.md: the existing T1.7 tests assert the
return-type contract for a native / MCP-stub / resource-stub tool but do not
prove *parity* across layers. These tests pin down behaviour that must be
identical no matter which backend handles the call:

- return type is always `str`
- success path returns the handler's output unchanged
- an exception inside the handler is converted to a str, never raised
- an unknown tool returns a str error, never raises
- sync and async handlers are both callable via the same surface
- caller-side cancellation (asyncio.wait_for) propagates identically across
  backends — the dispatch layer does not swallow or rewrite CancelledError

The runtime guard enforces per-tool timeouts by wrapping execute_by_name in
asyncio.wait_for, so these tests assert the contract the guard depends on.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

import pytest

from agent.core.models import ToolDef, ToolGroup, ToolLoadingStrategy
from agent.runtime.tool_dispatch import ToolDispatch


# ── Backends under test ───────────────────────────────────────────────────

# A "backend" for this test is a handler shape that mirrors how real tools
# enter the dispatch registry. The dispatch layer treats them identically;
# that's the claim under test.

def _native_handler(value: str = "ok", **_: Any) -> str:
    """Sync built-in tool."""
    return f"native:{value}"


async def _mcp_handler(value: str = "ok", **_: Any) -> str:
    """Async MCP-proxied tool handler."""
    return f"mcp:{value}"


async def _resource_handler(value: str = "ok", **_: Any) -> str:
    """Async resource-like read handler."""
    return f"resource:{value}"


BACKENDS: list[tuple[str, Callable[..., Any], str]] = [
    ("native", _native_handler, "native:ok"),
    ("mcp", _mcp_handler, "mcp:ok"),
    ("resource", _resource_handler, "resource:ok"),
]


def _register(dispatch: ToolDispatch, name: str, handler: Callable[..., Any], group: ToolGroup) -> None:
    td = ToolDef(
        name=name,
        description=f"{name} contract stub",
        parameters=[],
        tool_group=group,
        loading_strategy=ToolLoadingStrategy.ALWAYS,
    )
    dispatch.register(td, handler)


# ── Parity assertions ─────────────────────────────────────────────────────

@pytest.mark.parametrize("label,handler,expected", BACKENDS, ids=[b[0] for b in BACKENDS])
def test_success_returns_str(label: str, handler: Callable[..., Any], expected: str) -> None:
    """Every backend returns the handler's string output unchanged."""
    dispatch = ToolDispatch()
    _register(dispatch, f"tool_{label}", handler, ToolGroup.CORE)

    result = asyncio.run(dispatch.execute_by_name(f"tool_{label}", {}))

    assert isinstance(result, str)
    assert result == expected


@pytest.mark.parametrize("label,handler,expected", BACKENDS, ids=[b[0] for b in BACKENDS])
def test_handler_exception_is_converted_to_str(
    label: str, handler: Callable[..., Any], expected: str,
) -> None:
    """An exception inside a handler must not escape execute_by_name."""
    dispatch = ToolDispatch()

    def _sync_boom(**_: Any) -> str:
        raise RuntimeError(f"boom_{label}")

    async def _async_boom(**_: Any) -> str:
        raise RuntimeError(f"boom_{label}")

    # Use the same handler shape as the backend under test (sync vs async).
    boom = _sync_boom if asyncio.iscoroutinefunction(handler) is False else _async_boom
    _register(dispatch, f"tool_{label}_boom", boom, ToolGroup.CORE)

    result = asyncio.run(dispatch.execute_by_name(f"tool_{label}_boom", {}))

    assert isinstance(result, str)
    assert f"boom_{label}" in result


def test_unknown_tool_returns_str_error() -> None:
    """The str-return contract holds even when the tool doesn't exist."""
    dispatch = ToolDispatch()

    result = asyncio.run(dispatch.execute_by_name("does_not_exist", {}))

    assert isinstance(result, str)
    assert "does_not_exist" in result.lower() or "unknown" in result.lower()


@pytest.mark.parametrize("label,handler,_", BACKENDS, ids=[b[0] for b in BACKENDS])
def test_caller_side_timeout_propagates(
    label: str, handler: Callable[..., Any], _: str,
) -> None:
    """A slow handler is cancelled by the caller's asyncio.wait_for.

    This is the contract the RuntimeGuard relies on: the dispatch layer does
    not block cancellation on any backend.
    """
    dispatch = ToolDispatch()

    async def _slow(**_: Any) -> str:
        await asyncio.sleep(5)
        return "never"

    _register(dispatch, f"tool_{label}_slow", _slow, ToolGroup.CORE)

    async def _run() -> None:
        await asyncio.wait_for(
            dispatch.execute_by_name(f"tool_{label}_slow", {}),
            timeout=0.05,
        )

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(_run())


def test_sync_and_async_handlers_are_interchangeable() -> None:
    """Dispatch accepts both sync and coroutine handlers without special-casing."""
    dispatch = ToolDispatch()

    def sync(**_: Any) -> str:
        return "sync-out"

    async def async_(**_: Any) -> str:
        return "async-out"

    _register(dispatch, "sync_tool", sync, ToolGroup.CORE)
    _register(dispatch, "async_tool", async_, ToolGroup.CORE)

    sync_result = asyncio.run(dispatch.execute_by_name("sync_tool", {}))
    async_result = asyncio.run(dispatch.execute_by_name("async_tool", {}))

    assert isinstance(sync_result, str) and sync_result == "sync-out"
    assert isinstance(async_result, str) and async_result == "async-out"


def test_arg_validation_error_is_str_not_exception() -> None:
    """Missing required params return a str error, not a raise."""
    dispatch = ToolDispatch()

    from agent.core.models import ToolParameter

    td = ToolDef(
        name="needs_arg",
        description="requires q",
        parameters=[ToolParameter(name="q", type="string", description="query", required=True)],
        tool_group=ToolGroup.CORE,
        loading_strategy=ToolLoadingStrategy.ALWAYS,
    )
    dispatch.register(td, lambda **kw: f"got:{kw.get('q')}")

    result = asyncio.run(dispatch.execute_by_name("needs_arg", {}))

    assert isinstance(result, str)
    assert "q" in result.lower() or "missing" in result.lower()
