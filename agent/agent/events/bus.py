"""In-process event bus with per-session pub/sub and replay.

The runtime publishes `AgentEvent`s for a session; consumers subscribe to
the same session_id and receive events as they arrive. On reconnect,
consumers can pass `since_seq` to replay recent events from an in-memory
ring buffer (matching what a Last-Event-ID reconnection would need).

Subscribers auto-close their iterator when they receive a `StreamEnd`
event for the session — no polling of session state required.

Swap-in plan: a `RedisEventBus` implementation with the same `EventBus`
Protocol replaces this without touching runtime call sites (Phase 3).
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from typing import AsyncIterator, Deque, Protocol

from agent.events.schema import AgentEvent, StreamEnd


class EventBus(Protocol):
    """Minimum contract for session-scoped event pub/sub."""

    async def publish(self, session_id: str, event: AgentEvent) -> None:
        ...

    async def subscribe(
        self,
        session_id: str,
        *,
        since_seq: int | None = None,
    ) -> AsyncIterator[AgentEvent]:
        ...

    async def close_session(self, session_id: str) -> None:
        ...


# Sentinel pushed into subscriber queues to signal graceful termination
# (as opposed to a delivered AgentEvent).
_CLOSE = object()


class InMemoryEventBus:
    """Single-process EventBus: asyncio.Queue per subscriber, ring-buffer replay."""

    def __init__(self, *, replay_buffer_size: int = 1024) -> None:
        self._replay_buffer_size = replay_buffer_size
        self._buffers: dict[str, Deque[AgentEvent]] = defaultdict(
            lambda: deque(maxlen=replay_buffer_size)
        )
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._seq_counters: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def publish(self, session_id: str, event: AgentEvent) -> None:
        async with self._lock:
            # Assign a monotonic seq per session. Callers may pre-set it (e.g.,
            # when replaying from a durable store); if unset (0), we stamp.
            if event.seq == 0:
                self._seq_counters[session_id] += 1
                event.seq = self._seq_counters[session_id]
            else:
                self._seq_counters[session_id] = max(
                    self._seq_counters[session_id], event.seq
                )
            self._buffers[session_id].append(event)
            queues = list(self._subscribers.get(session_id, ()))
        for q in queues:
            await q.put(event)
            if isinstance(event, StreamEnd):
                # Signal iterator to close after yielding the stream_end event.
                await q.put(_CLOSE)

    async def subscribe(
        self,
        session_id: str,
        *,
        since_seq: int | None = None,
    ) -> AsyncIterator[AgentEvent]:
        queue: asyncio.Queue = asyncio.Queue()

        async with self._lock:
            # Replay: drain buffered events newer than since_seq into the queue
            # before registering, so we don't double-deliver.
            if since_seq is not None and session_id in self._buffers:
                for ev in self._buffers[session_id]:
                    if ev.seq > since_seq:
                        await queue.put(ev)
            self._subscribers[session_id].append(queue)

        try:
            while True:
                item = await queue.get()
                if item is _CLOSE:
                    return
                # mypy: item is an AgentEvent because _CLOSE is the only sentinel
                yield item  # type: ignore[misc]
                if isinstance(item, StreamEnd):
                    # StreamEnd publishers also enqueue _CLOSE right after, but
                    # exit eagerly so late subscribers on a finished stream
                    # still terminate cleanly.
                    return
        finally:
            async with self._lock:
                subs = self._subscribers.get(session_id)
                if subs and queue in subs:
                    subs.remove(queue)
                if subs is not None and not subs:
                    self._subscribers.pop(session_id, None)

    async def close_session(self, session_id: str) -> None:
        """Drop replay buffer + disconnect any live subscribers for a session."""
        async with self._lock:
            self._buffers.pop(session_id, None)
            queues = self._subscribers.pop(session_id, [])
        for q in queues:
            await q.put(_CLOSE)

    # ---- test/debug helpers ------------------------------------------------

    def _buffered(self, session_id: str) -> list[AgentEvent]:
        """Return a snapshot of the replay buffer (tests only)."""
        return list(self._buffers.get(session_id, ()))

    def _subscriber_count(self, session_id: str) -> int:
        """Return number of live subscribers (tests only)."""
        return len(self._subscribers.get(session_id, ()))
