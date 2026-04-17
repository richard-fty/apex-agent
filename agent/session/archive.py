"""SQLite + FTS5 session archive.

Append-only event log with BM25 full-text search. Replaces the JSON-file
SessionStore for durable persistence with positional reads and recall queries.

Key properties:
  - Append-only: INSERT only, never UPDATE/DELETE on events
  - WAL mode: concurrent readers (TUI) + single writer (harness)
  - FTS5: BM25-ranked text search for recall_session
  - Positional reads: getEvents(session_id, after=cursor)
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id       TEXT PRIMARY KEY,
    project_id       TEXT,
    model            TEXT NOT NULL,
    context_strategy TEXT NOT NULL,
    state            TEXT DEFAULT 'idle',
    stop_reason      TEXT,
    created_at       REAL DEFAULT (unixepoch('subsec')),
    metadata         TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT NOT NULL REFERENCES sessions(session_id),
    seq              INTEGER NOT NULL,
    event_type       TEXT NOT NULL,
    timestamp        REAL NOT NULL,
    payload          TEXT NOT NULL,
    content_text     TEXT,
    UNIQUE(session_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, seq);

CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    content_text,
    content='events',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, content_text) VALUES (new.id, new.content_text);
END;
"""


def _extract_searchable_text(event_type: str, payload: dict[str, Any]) -> str:
    """Pull human-readable text from an event for FTS5 indexing."""
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


class SessionArchive:
    """SQLite + FTS5 durable session archive."""

    def __init__(self, db_path: str = "results/sessions/archive.db") -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(_SCHEMA)
        self._seq_cache: dict[str, int] = {}

    def create_session(
        self,
        *,
        session_id: str,
        model: str,
        context_strategy: str,
        project_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO sessions "
            "(session_id, project_id, model, context_strategy, metadata) "
            "VALUES (?, ?, ?, ?, ?)",
            [session_id, project_id, model, context_strategy,
             json.dumps(metadata or {})],
        )
        self.db.commit()
        self._seq_cache[session_id] = 0

    def emit_event(
        self,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> int:
        """Append an event. Returns the sequence number."""
        seq = self._seq_cache.get(session_id, 0) + 1
        self._seq_cache[session_id] = seq
        content_text = _extract_searchable_text(event_type, payload)
        self.db.execute(
            "INSERT INTO events (session_id, seq, event_type, timestamp, payload, content_text) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [session_id, seq, event_type, time.time(), json.dumps(payload, default=str),
             content_text],
        )
        self.db.commit()
        return seq

    def get_events(
        self,
        session_id: str,
        after: int = 0,
    ) -> list[dict[str, Any]]:
        """Read events, optionally after a cursor position."""
        rows = self.db.execute(
            "SELECT seq, event_type, timestamp, payload FROM events "
            "WHERE session_id = ? AND seq > ? ORDER BY seq",
            [session_id, after],
        ).fetchall()
        return [
            {
                "seq": r["seq"],
                "type": r["event_type"],
                "timestamp": r["timestamp"],
                "payload": json.loads(r["payload"]),
            }
            for r in rows
        ]

    def recall(
        self,
        session_id: str,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """BM25-ranked full-text search within a session."""
        rows = self.db.execute(
            "SELECT e.seq, e.event_type, e.payload, "
            "snippet(events_fts, 0, '»', '«', '...', 64) as fragment "
            "FROM events e "
            "JOIN events_fts ON e.id = events_fts.rowid "
            "WHERE e.session_id = ? AND events_fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            [session_id, query, limit],
        ).fetchall()
        return [
            {
                "seq": r["seq"],
                "event_type": r["event_type"],
                "fragment": r["fragment"],
                "payload": json.loads(r["payload"]),
            }
            for r in rows
        ]

    def update_session_state(
        self,
        session_id: str,
        state: str,
        stop_reason: str | None = None,
    ) -> None:
        self.db.execute(
            "UPDATE sessions SET state = ?, stop_reason = ? WHERE session_id = ?",
            [state, stop_reason, session_id],
        )
        self.db.commit()

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            [session_id],
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        if result.get("metadata"):
            result["metadata"] = json.loads(result["metadata"])
        return result

    def close(self) -> None:
        self.db.close()
