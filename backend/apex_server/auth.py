"""Authentication: users + server-side cookie sessions on Postgres."""

from __future__ import annotations

import os
import secrets
import threading
import time
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

try:  # pragma: no cover - depends on optional runtime dependency
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover
    psycopg = None
    dict_row = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    token       TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  DOUBLE PRECISION NOT NULL,
    expires_at  DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id);
"""

SESSION_COOKIE = "apex_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 30
MIN_PASSWORD_LEN = 8


@dataclass
class User:
    id: str
    username: str


@dataclass
class Credentials:
    username: str
    password: str


class AuthStore:
    """Postgres-backed users + auth_sessions."""

    def __init__(self, dsn: str | None = None) -> None:
        if dsn is None:
            dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise RuntimeError("DATABASE_URL is required for Postgres auth storage.")
        if psycopg is None:  # pragma: no cover - depends on optional dependency
            raise RuntimeError(
                "psycopg is required for Postgres storage. Install psycopg[binary] first."
            )
        self._lock = threading.RLock()
        self.db = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
        with self._lock, self.db.cursor() as cur:
            cur.execute(_SCHEMA)
        self._hasher = PasswordHasher()

    def _hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def _verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except VerifyMismatchError:
            return False
        except Exception:
            return False

    def create_user(self, *, username: str, password: str) -> User:
        if len(password) < MIN_PASSWORD_LEN:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LEN} characters")
        if not username or len(username) > 64 or not username.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Username must be 1–64 alphanumeric (plus _ or -)")
        user_id = secrets.token_hex(16)
        now = time.time()
        try:
            with self._lock, self.db.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (id, username, password_hash, created_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    [user_id, username, self._hash(password), now],
                )
        except Exception as exc:
            raise ValueError("Registration failed") from exc
        return User(id=user_id, username=username)

    def find_by_username(self, username: str) -> tuple[User, str] | None:
        with self._lock, self.db.cursor() as cur:
            cur.execute(
                "SELECT id, username, password_hash FROM users WHERE username = %s",
                [username],
            )
            row = cur.fetchone()
        if row is None:
            return None
        return User(id=row["id"], username=row["username"]), row["password_hash"]

    def get_user(self, user_id: str) -> User | None:
        with self._lock, self.db.cursor() as cur:
            cur.execute("SELECT id, username FROM users WHERE id = %s", [user_id])
            row = cur.fetchone()
        if row is None:
            return None
        return User(id=row["id"], username=row["username"])

    def authenticate(self, *, username: str, password: str) -> User | None:
        existing = self.find_by_username(username)
        if existing is None:
            self._verify(self._hash("dummy-for-timing"), password)
            return None
        user, stored_hash = existing
        if self._verify(stored_hash, password):
            return user
        return None

    def create_session(self, user_id: str) -> tuple[str, float]:
        token = secrets.token_urlsafe(32)
        now = time.time()
        expires_at = now + SESSION_TTL_SECONDS
        with self._lock, self.db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auth_sessions (token, user_id, created_at, expires_at)
                VALUES (%s, %s, %s, %s)
                """,
                [token, user_id, now, expires_at],
            )
        return token, expires_at

    def resolve_session(self, token: str) -> User | None:
        now = time.time()
        with self._lock, self.db.cursor() as cur:
            cur.execute(
                "SELECT token, user_id, expires_at FROM auth_sessions WHERE token = %s",
                [token],
            )
            row = cur.fetchone()
            if row is None or row["expires_at"] < now:
                if row is not None:
                    cur.execute("DELETE FROM auth_sessions WHERE token = %s", [token])
                return None
            new_expiry = now + SESSION_TTL_SECONDS
            cur.execute(
                "UPDATE auth_sessions SET expires_at = %s WHERE token = %s",
                [new_expiry, token],
            )
        return self.get_user(row["user_id"])

    def delete_session(self, token: str) -> None:
        with self._lock, self.db.cursor() as cur:
            cur.execute("DELETE FROM auth_sessions WHERE token = %s", [token])


def _dev_bypass_enabled() -> bool:
    if os.environ.get("ENV", "").lower() == "production":
        return False
    return os.environ.get("APEX_DEV_BYPASS_AUTH", "").lower() in {"1", "true", "yes"}


def dev_bypass_user(store: AuthStore) -> User:
    existing = store.find_by_username("dev")
    if existing is not None:
        return existing[0]
    return store.create_user(username="dev", password="dev-bypass-password")
