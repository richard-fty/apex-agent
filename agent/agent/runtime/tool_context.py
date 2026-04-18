"""Per-turn tool execution context.

Carries the current session_id/turn_id, event bus, and artifact store into
tool handlers without changing the universal hands API (which takes `**kwargs`
plus a return of type str). Tools that want to emit artifacts or events
read `get_tool_context()` at run time.

Why contextvars: tool handlers today are plain callables; passing a context
parameter would break every existing handler. A ContextVar scoped to the
runtime's dispatch call sets/resets the context per tool invocation.
"""

from __future__ import annotations

import time
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from agent.artifacts import ArtifactStore
    from agent.events import EventBus


@dataclass
class ToolContext:
    """The ambient context a tool can read during execution."""

    session_id: str
    turn_id: str | None
    event_bus: "EventBus"
    artifact_store: "ArtifactStore | None" = None
    # extra: per-call bag tools can stash values into if they want correlation
    extras: dict[str, Any] = field(default_factory=dict)


_current: ContextVar["ToolContext | None"] = ContextVar("tool_context", default=None)


def get_tool_context() -> "ToolContext | None":
    """Return the current tool context, or None if no tool is executing."""
    return _current.get()


def set_tool_context(ctx: "ToolContext | None") -> Token:
    """Install a ToolContext for the duration of a `with`/try block.

    Callers should pair this with `_current.reset(token)` in a finally clause,
    or use the `tool_context_scope` helper below.
    """
    return _current.set(ctx)


def reset_tool_context(token: Token) -> None:
    _current.reset(token)


class tool_context_scope:  # noqa: N801 - lowercase context manager convention
    """`with tool_context_scope(ctx): ...` — ensures set/reset is paired."""

    def __init__(self, ctx: "ToolContext | None") -> None:
        self._ctx = ctx
        self._token: Token | None = None

    def __enter__(self) -> "ToolContext | None":
        self._token = _current.set(self._ctx)
        return self._ctx

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._token is not None:
            _current.reset(self._token)
            self._token = None


# ---- Helpers tools can call --------------------------------------------


async def emit_artifact_created(*, spec: Any) -> str | None:
    """Create an artifact for the current session and emit the event.

    Returns the artifact_id, or None if no store is available (silent no-op so
    tools run fine outside a server context, e.g. in unit tests).
    """
    from agent.events.schema import ArtifactCreated

    ctx = get_tool_context()
    if ctx is None or ctx.artifact_store is None:
        return None
    artifact = await ctx.artifact_store.create(ctx.session_id, spec)
    await ctx.event_bus.publish(
        ctx.session_id,
        ArtifactCreated(
            session_id=ctx.session_id,
            turn_id=ctx.turn_id,
            artifact_id=artifact.id,
            kind=spec.kind,
            name=spec.name,
            language=spec.language,
            mime=spec.mime,
            description=spec.description,
        ),
    )
    return artifact.id


async def emit_artifact_append(artifact_id: str, text: str) -> None:
    from agent.events.schema import ArtifactPatch, ArtifactPatchOp

    ctx = get_tool_context()
    if ctx is None or ctx.artifact_store is None or not artifact_id:
        return
    await ctx.artifact_store.append(ctx.session_id, artifact_id, text.encode("utf-8"))
    await ctx.event_bus.publish(
        ctx.session_id,
        ArtifactPatch(
            session_id=ctx.session_id,
            turn_id=ctx.turn_id,
            artifact_id=artifact_id,
            op=ArtifactPatchOp.APPEND,
            text=text,
        ),
    )


async def emit_artifact_replace(artifact_id: str, content: str) -> None:
    from agent.events.schema import ArtifactPatch, ArtifactPatchOp

    ctx = get_tool_context()
    if ctx is None or ctx.artifact_store is None or not artifact_id:
        return
    await ctx.artifact_store.replace(ctx.session_id, artifact_id, content.encode("utf-8"))
    await ctx.event_bus.publish(
        ctx.session_id,
        ArtifactPatch(
            session_id=ctx.session_id,
            turn_id=ctx.turn_id,
            artifact_id=artifact_id,
            op=ArtifactPatchOp.REPLACE,
            content=content,
        ),
    )


async def emit_artifact_finalized(artifact_id: str) -> None:
    from agent.events.schema import ArtifactFinalized

    ctx = get_tool_context()
    if ctx is None or ctx.artifact_store is None or not artifact_id:
        return
    artifact = await ctx.artifact_store.finalize(ctx.session_id, artifact_id)
    await ctx.event_bus.publish(
        ctx.session_id,
        ArtifactFinalized(
            session_id=ctx.session_id,
            turn_id=ctx.turn_id,
            artifact_id=artifact_id,
            size=artifact.size,
            checksum=artifact.checksum,
        ),
    )
