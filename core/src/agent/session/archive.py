"""Postgres durable session archive.

This is the canonical session storage backend for the app. A valid
``DATABASE_URL`` (or explicit DSN) is required.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

try:  # pragma: no cover - depends on optional runtime dependency
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover
    psycopg = None
    dict_row = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id       TEXT PRIMARY KEY,
    project_id       TEXT,
    model            TEXT NOT NULL,
    context_strategy TEXT NOT NULL,
    state            TEXT DEFAULT 'idle',
    stop_reason      TEXT,
    created_at       DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW()),
    metadata         JSONB,
    owner_user_id    TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id               BIGSERIAL PRIMARY KEY,
    session_id       TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    seq              INTEGER NOT NULL,
    event_type       TEXT NOT NULL,
    timestamp        DOUBLE PRECISION NOT NULL,
    payload          JSONB NOT NULL,
    content_text     TEXT,
    UNIQUE(session_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_sessions_owner ON sessions(owner_user_id, created_at DESC);
"""


def _extract_searchable_text(event_type: str, payload: dict[str, Any]) -> str:
    """Pull human-readable text from an event for recall queries."""
    if event_type in ("user_message_added", "user_input_received"):
        return payload.get("content", payload.get("user_input", ""))
    if event_type == "assistant_message_added":
        msg = payload.get("message", {})
        return msg.get("content", "") if isinstance(msg, dict) else ""
    if event_type in ("tool_finished", "tool_message_added"):
        name = payload.get("name", payload.get("tool_name", ""))
        content = payload.get("content", "")
        return f"{name} {content}"
    if event_type == "plan_created":
        tasks = payload.get("tasks", [])
        return " ".join(t.get("title", "") for t in tasks)
    if event_type == "plan_task_updated":
        return f"{payload.get('task_id', '')} {payload.get('status', '')} {payload.get('note', '')}"
    if event_type == "fact_pinned":
        return payload.get("fact", "")
    return ""


def _coerce_json(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return value


class SessionArchive:
    """Postgres durable session archive."""

    def __init__(self, dsn: str | None = None) -> None:
        if dsn is None:
            dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise RuntimeError("DATABASE_URL is required for Postgres session storage.")
        if psycopg is None:  # pragma: no cover - depends on optional dependency
            raise RuntimeError(
                "psycopg is required for Postgres storage. Install psycopg[binary] first."
            )
        self._dsn = dsn
        self._lock = threading.RLock()
        self.db = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
        with self._lock, self.db.cursor() as cur:
            cur.execute(_SCHEMA)
        self._seq_cache: dict[str, int] = {}

    def create_session(
        self,
        *,
        session_id: str,
        model: str,
        context_strategy: str,
        project_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        owner_user_id: str | None = None,
    ) -> None:
        with self._lock, self.db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sessions (
                    session_id, project_id, model, context_strategy, metadata, owner_user_id
                ) VALUES (%s, %s, %s, %s, CAST(%s AS JSONB), %s)
                ON CONFLICT (session_id) DO NOTHING
                """,
                [
                    session_id,
                    project_id,
                    model,
                    context_strategy,
                    json.dumps(metadata or {}, default=str),
                    owner_user_id,
                ],
            )
        self._seq_cache[session_id] = self.get_last_seq(session_id)

    def emit_event(
        self,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> int:
        seq = self._seq_cache.get(session_id, 0) + 1
        self._seq_cache[session_id] = seq
        content_text = _extract_searchable_text(event_type, payload)
        with self._lock, self.db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO events (
                    session_id, seq, event_type, timestamp, payload, content_text
                ) VALUES (%s, %s, %s, %s, CAST(%s AS JSONB), %s)
                """,
                [
                    session_id,
                    seq,
                    event_type,
                    time.time(),
                    json.dumps(payload, default=str),
                    content_text,
                ],
            )
        return seq

    def get_last_seq(self, session_id: str) -> int:
        with self._lock, self.db.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(MAX(seq), 0) AS last_seq FROM events WHERE session_id = %s",
                [session_id],
            )
            row = cur.fetchone()
        last_seq = int(row["last_seq"]) if row is not None else 0
        self._seq_cache[session_id] = last_seq
        return last_seq

    def get_events(
        self,
        session_id: str,
        after: int = 0,
    ) -> list[dict[str, Any]]:
        with self._lock, self.db.cursor() as cur:
            cur.execute(
                """
                SELECT seq, event_type, timestamp, payload
                FROM events
                WHERE session_id = %s AND seq > %s
                ORDER BY seq
                """,
                [session_id, after],
            )
            rows = cur.fetchall()
        return [
            {
                "seq": row["seq"],
                "type": row["event_type"],
                "timestamp": row["timestamp"],
                "payload": _coerce_json(row["payload"]) or {},
            }
            for row in rows
        ]

    def recall(
        self,
        session_id: str,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        with self._lock, self.db.cursor() as cur:
            cur.execute(
                """
                SELECT seq, event_type, payload, LEFT(COALESCE(content_text, ''), 240) AS fragment
                FROM events
                WHERE session_id = %s
                  AND (
                    COALESCE(content_text, '') ILIKE %s
                    OR CAST(payload AS TEXT) ILIKE %s
                  )
                ORDER BY seq DESC
                LIMIT %s
                """,
                [session_id, pattern, pattern, limit],
            )
            rows = cur.fetchall()
        return [
            {
                "seq": row["seq"],
                "event_type": row["event_type"],
                "fragment": row["fragment"],
                "payload": _coerce_json(row["payload"]) or {},
            }
            for row in rows
        ]

    def update_session_state(
        self,
        session_id: str,
        state: str,
        stop_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._lock, self.db.cursor() as cur:
            if metadata is None:
                cur.execute(
                    "UPDATE sessions SET state = %s, stop_reason = %s WHERE session_id = %s",
                    [state, stop_reason, session_id],
                )
            else:
                cur.execute(
                    """
                    UPDATE sessions
                    SET state = %s, stop_reason = %s, metadata = CAST(%s AS JSONB)
                    WHERE session_id = %s
                    """,
                    [state, stop_reason, json.dumps(metadata, default=str), session_id],
                )

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock, self.db.cursor() as cur:
            cur.execute("SELECT * FROM sessions WHERE session_id = %s", [session_id])
            row = cur.fetchone()
        if row is None:
            return None
        result = dict(row)
        result["metadata"] = _coerce_json(result.get("metadata")) or {}
        return result

    def list_session_ids_for_user(self, owner_user_id: str) -> list[str]:
        with self._lock, self.db.cursor() as cur:
            cur.execute(
                """
                SELECT session_id
                FROM sessions
                WHERE owner_user_id = %s
                ORDER BY created_at DESC
                """,
                [owner_user_id],
            )
            rows = cur.fetchall()
        return [str(row["session_id"]) for row in rows]

    def delete_session(self, session_id: str) -> None:
        with self._lock, self.db.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE session_id = %s", [session_id])
        self._seq_cache.pop(session_id, None)

    def close(self) -> None:
        self.db.close()
