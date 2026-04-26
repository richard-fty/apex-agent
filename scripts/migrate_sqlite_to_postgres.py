"""One-shot migration from the legacy SQLite app database to Postgres.

Usage:
    ./.venv/bin/python scripts/migrate_sqlite_to_postgres.py \
        --sqlite-path results/apex.db \
        --database-url postgresql://user:pass@host/dbname
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from typing import Any

import psycopg

from apex_server.auth import AuthStore
from apex_server.wealth_store import WealthStore
from agent.session.archive import SessionArchive


def _json_dump(value: Any) -> str:
    return json.dumps(value, default=str)


def migrate(sqlite_path: str, database_url: str) -> None:
    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row

    # Ensure destination schema exists.
    archive = SessionArchive(database_url)
    auth = AuthStore(database_url)
    wealth = WealthStore(database_url)
    archive.close()
    auth.db.close()
    wealth.db.close()

    with psycopg.connect(database_url, autocommit=True) as dst:
        with dst.cursor() as cur:
            session_rows = src.execute("SELECT * FROM sessions ORDER BY created_at ASC").fetchall()
            for row in session_rows:
                cur.execute(
                    """
                    INSERT INTO sessions (
                        session_id, project_id, model, context_strategy, state,
                        stop_reason, created_at, metadata, owner_user_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, CAST(%s AS JSONB), %s)
                    ON CONFLICT (session_id) DO UPDATE SET
                        project_id = excluded.project_id,
                        model = excluded.model,
                        context_strategy = excluded.context_strategy,
                        state = excluded.state,
                        stop_reason = excluded.stop_reason,
                        created_at = excluded.created_at,
                        metadata = excluded.metadata,
                        owner_user_id = excluded.owner_user_id
                    """,
                    [
                        row["session_id"],
                        row["project_id"],
                        row["model"],
                        row["context_strategy"],
                        row["state"],
                        row["stop_reason"],
                        row["created_at"],
                        row["metadata"] or _json_dump({}),
                        row["owner_user_id"] if "owner_user_id" in row.keys() else None,
                    ],
                )

            event_rows = src.execute("SELECT * FROM events ORDER BY id ASC").fetchall()
            for row in event_rows:
                cur.execute(
                    """
                    INSERT INTO events (
                        id, session_id, seq, event_type, timestamp, payload, content_text
                    ) VALUES (%s, %s, %s, %s, %s, CAST(%s AS JSONB), %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    [
                        row["id"],
                        row["session_id"],
                        row["seq"],
                        row["event_type"],
                        row["timestamp"],
                        row["payload"],
                        row["content_text"],
                    ],
                )

            user_rows = src.execute("SELECT * FROM users ORDER BY created_at ASC").fetchall()
            for row in user_rows:
                cur.execute(
                    """
                    INSERT INTO users (id, username, password_hash, created_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        username = excluded.username,
                        password_hash = excluded.password_hash,
                        created_at = excluded.created_at
                    """,
                    [row["id"], row["username"], row["password_hash"], row["created_at"]],
                )

            auth_rows = src.execute("SELECT * FROM auth_sessions ORDER BY created_at ASC").fetchall()
            for row in auth_rows:
                cur.execute(
                    """
                    INSERT INTO auth_sessions (token, user_id, created_at, expires_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (token) DO UPDATE SET
                        user_id = excluded.user_id,
                        created_at = excluded.created_at,
                        expires_at = excluded.expires_at
                    """,
                    [row["token"], row["user_id"], row["created_at"], row["expires_at"]],
                )

            if _table_exists(src, "wealth_profiles"):
                profile_rows = src.execute(
                    "SELECT * FROM wealth_profiles ORDER BY updated_at ASC"
                ).fetchall()
                for row in profile_rows:
                    cur.execute(
                        """
                        INSERT INTO wealth_profiles (user_id, profile_json, updated_at)
                        VALUES (%s, CAST(%s AS JSONB), %s)
                        ON CONFLICT (user_id) DO UPDATE SET
                            profile_json = excluded.profile_json,
                            updated_at = excluded.updated_at
                        """,
                        [row["user_id"], row["profile_json"], row["updated_at"]],
                    )

            if _table_exists(src, "wealth_checklist_items"):
                checklist_rows = src.execute(
                    """
                    SELECT user_id, artifact_id, item_index, text, completed, completed_at
                    FROM wealth_checklist_items
                    ORDER BY user_id ASC, artifact_id ASC, item_index ASC
                    """
                ).fetchall()
                for row in checklist_rows:
                    cur.execute(
                        """
                        INSERT INTO wealth_checklist_items (
                            user_id, artifact_id, item_index, text, completed, completed_at
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (user_id, artifact_id, item_index) DO UPDATE SET
                            text = excluded.text,
                            completed = excluded.completed,
                            completed_at = excluded.completed_at
                        """,
                        [
                            row["user_id"],
                            row["artifact_id"],
                            row["item_index"],
                            row["text"],
                            bool(row["completed"]),
                            row["completed_at"],
                        ],
                    )

            # Advance the events id sequence to the imported max id.
            cur.execute(
                """
                SELECT setval(
                    pg_get_serial_sequence('events', 'id'),
                    COALESCE((SELECT MAX(id) FROM events), 1),
                    true
                )
                """
            )

    src.close()


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        [table_name],
    ).fetchone()
    return row is not None


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate legacy SQLite data into Postgres.")
    parser.add_argument("--sqlite-path", required=True, help="Path to the existing SQLite database")
    parser.add_argument("--database-url", required=True, help="Destination Postgres DSN")
    args = parser.parse_args()
    migrate(args.sqlite_path, args.database_url)


if __name__ == "__main__":
    main()
