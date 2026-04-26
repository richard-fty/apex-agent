"""User-scoped wealth storage on Postgres."""

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
CREATE TABLE IF NOT EXISTS wealth_profiles (
    user_id      TEXT PRIMARY KEY,
    profile_json JSONB NOT NULL,
    updated_at   DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS wealth_checklist_items (
    user_id       TEXT NOT NULL,
    artifact_id   TEXT NOT NULL,
    item_index    INTEGER NOT NULL,
    text          TEXT NOT NULL,
    completed     BOOLEAN NOT NULL DEFAULT FALSE,
    completed_at  DOUBLE PRECISION,
    PRIMARY KEY (user_id, artifact_id, item_index)
);

CREATE INDEX IF NOT EXISTS idx_wealth_checklist_user_artifact
ON wealth_checklist_items(user_id, artifact_id);
"""


def _coerce_json(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return value


class WealthStore:
    """Postgres-backed user profile and checklist state."""

    def __init__(self, dsn: str | None = None) -> None:
        if dsn is None:
            dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise RuntimeError("DATABASE_URL is required for Postgres wealth storage.")
        if psycopg is None:  # pragma: no cover - depends on optional dependency
            raise RuntimeError(
                "psycopg is required for Postgres storage. Install psycopg[binary] first."
            )
        self._lock = threading.RLock()
        self.db = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
        with self._lock, self.db.cursor() as cur:
            cur.execute(_SCHEMA)

    def upsert_profile(self, user_id: str, profile: dict[str, Any]) -> None:
        now = time.time()
        with self._lock, self.db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO wealth_profiles (user_id, profile_json, updated_at)
                VALUES (%s, CAST(%s AS JSONB), %s)
                ON CONFLICT(user_id) DO UPDATE
                SET profile_json = excluded.profile_json,
                    updated_at = excluded.updated_at
                """,
                [user_id, json.dumps(profile, default=str), now],
            )

    def get_profile(self, user_id: str) -> dict[str, Any] | None:
        with self._lock, self.db.cursor() as cur:
            cur.execute(
                "SELECT profile_json FROM wealth_profiles WHERE user_id = %s",
                [user_id],
            )
            row = cur.fetchone()
        if row is None:
            return None
        return _coerce_json(row["profile_json"])

    def set_checklist_item(
        self,
        *,
        user_id: str,
        artifact_id: str,
        item_index: int,
        text: str,
        completed: bool,
    ) -> None:
        completed_at = time.time() if completed else None
        with self._lock, self.db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO wealth_checklist_items (
                    user_id, artifact_id, item_index, text, completed, completed_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(user_id, artifact_id, item_index) DO UPDATE
                SET text = excluded.text,
                    completed = excluded.completed,
                    completed_at = excluded.completed_at
                """,
                [user_id, artifact_id, item_index, text, completed, completed_at],
            )

    def list_checklist_items(
        self,
        user_id: str,
        *,
        artifact_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock, self.db.cursor() as cur:
            if artifact_id:
                cur.execute(
                    """
                    SELECT artifact_id, item_index, text, completed, completed_at
                    FROM wealth_checklist_items
                    WHERE user_id = %s AND artifact_id = %s
                    ORDER BY item_index ASC
                    """,
                    [user_id, artifact_id],
                )
            else:
                cur.execute(
                    """
                    SELECT artifact_id, item_index, text, completed, completed_at
                    FROM wealth_checklist_items
                    WHERE user_id = %s
                    ORDER BY artifact_id ASC, item_index ASC
                    """,
                    [user_id],
                )
            rows = cur.fetchall()
        return [
            {
                "artifact_id": row["artifact_id"],
                "item_index": row["item_index"],
                "text": row["text"],
                "completed": bool(row["completed"]),
                "completed_at": row["completed_at"],
            }
            for row in rows
        ]
