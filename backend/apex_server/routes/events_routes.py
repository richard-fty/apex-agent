"""SSE event stream routes.

Stream-end semantics (resolved contractual decision):

``StreamEnd`` marks a **turn boundary**, not a connection close. After emitting
``StreamEnd`` for a session, the runtime may publish more events for subsequent
turns on the same session. The SSE handler therefore re-subscribes to the event
bus after receiving a ``StreamEnd`` so the same HTTP connection stays open across
multiple turns.

This means:

- Clients that close on ``stream_end`` will miss follow-up turns.
- Clients that correctly treat ``stream_end`` as turn-end will re-enter the
  listen loop and see the next turn's events on the same connection.
- On disconnect + reconnect, the client sends ``Last-Event-ID`` and the server
  replays all persisted events newer than that seq, then attaches to the live
  bus — so no events are lost even across process restarts.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from agent.events import AgentEvent, StreamEnd
from apex_server.deps import AppState, User, get_state, require_user
from apex_server.routes.session_support import owned_session


router = APIRouter(prefix="/sessions", tags=["sessions"])


async def load_replay_events(state: AppState, session_id: str, since_seq: int) -> list[AgentEvent]:
    """Load persisted typed events newer than `since_seq` for SSE replay."""
    return await state.session_store.list_events(session_id, since_seq=since_seq)


async def _next_live_event_with_disconnect(
    request: Request,
    subscription,
    *,
    poll_interval: float = 0.25,
) -> AgentEvent | None:
    """Wait for the next bus event while still noticing client disconnects."""
    next_task = asyncio.create_task(subscription.__anext__())
    try:
        while True:
            done, _ = await asyncio.wait({next_task}, timeout=poll_interval)
            if done:
                return await next_task
            if await request.is_disconnected():
                next_task.cancel()
                try:
                    await next_task
                except asyncio.CancelledError:
                    pass
                return None
    except StopAsyncIteration:
        return None


@router.get("/{session_id}/events")
async def stream_events(
    session_id: str,
    request: Request,
    last_event_id: str | None = None,
    user: User = Depends(require_user),
    state: AppState = Depends(get_state),
) -> EventSourceResponse:
    """Server-Sent Events stream of runtime events for a session.

    Contract:
    - replay persisted typed events newer than `Last-Event-ID` first
    - then attach to the live bus using the latest delivered seq as the cursor
    - keep the HTTP stream open across turns; `StreamEnd` marks a turn boundary,
      not the end of the SSE connection
    """
    await owned_session(session_id, user, state)
    since_seq = 0
    raw_last = last_event_id or request.headers.get("last-event-id")
    if raw_last:
        try:
            since_seq = int(raw_last)
        except ValueError:
            since_seq = 0

    def _encode_event(ev: AgentEvent) -> dict[str, str]:
        return {
            "id": str(ev.seq),
            "event": ev.type,
            "data": ev.model_dump_json(),
        }

    async def event_gen():
        cursor = since_seq

        # Durable replay first: survives reconnects even if the process restarts
        # or the in-memory bus buffer has been lost.
        replay = await load_replay_events(state, session_id, cursor)
        for ev in replay:
            cursor = max(cursor, ev.seq)
            yield _encode_event(ev)

        while True:
            if await request.is_disconnected():
                return

            subscription = state.event_bus.subscribe(
                session_id, since_seq=cursor
            ).__aiter__()
            while True:
                ev = await _next_live_event_with_disconnect(request, subscription)
                if ev is None:
                    break
                cursor = max(cursor, ev.seq)
                yield _encode_event(ev)
                if await request.is_disconnected():
                    return
                if isinstance(ev, StreamEnd):
                    # Turn boundary only; loop and subscribe again so the same
                    # SSE connection can remain open for the next turn.
                    break

            if await request.is_disconnected():
                return

            # Session was force-closed or the subscription ended without a
            # turn boundary. Avoid a tight reconnect loop.
            await asyncio.sleep(0.05)

    return EventSourceResponse(event_gen())
