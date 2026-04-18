"""Authentication: users + server-side cookie sessions.

MVP scope (per plan §7.0):

- Users have a username and an argon2-hashed password.
- Successful login issues a random session token, stored server-side with
  an expiry. The token is returned to the client as an HTTP-only, SameSite=Lax
  cookie (`apex_session`).
- `require_user` is a FastAPI dependency every protected route uses to resolve
  the current user from the cookie (or the `APEX_DEV_BYPASS_AUTH` dev door).
- argon2-cffi uses a constant-time `verify`, so timing-based user enumeration
  through login is not easy; the helper intentionally hashes even when the
  user does not exist so response time is the same.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    token       TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id);
"""

SESSION_COOKIE = "apex_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days, sliding
MIN_PASSWORD_LEN = 8


@dataclass
class User:
    id: str
    username: str


@dataclass
class Credentials:
    username: str
    password: str


# ---------------------------------------------------------------------------
# Auth store
# ---------------------------------------------------------------------------


class AuthStore:
    """SQLite-backed users + auth_sessions."""

    def __init__(self, db_path: str | Path = "results/apex.db") -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(_SCHEMA)
        self._hasher = PasswordHasher()

    # ---- password helpers ----------------------------------------------

    def _hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def _verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except VerifyMismatchError:
            return False
        except Exception:
            return False

    # ---- users ----------------------------------------------------------

    def create_user(self, *, username: str, password: str) -> User:
        if len(password) < MIN_PASSWORD_LEN:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LEN} characters")
        if not username or len(username) > 64 or not username.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Username must be 1–64 alphanumeric (plus _ or -)")
        user_id = secrets.token_hex(16)
        now = time.time()
        try:
            self.db.execute(
                "INSERT INTO users (id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
                [user_id, username, self._hash(password), now],
            )
            self.db.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError("Registration failed") from exc
        return User(id=user_id, username=username)

    def find_by_username(self, username: str) -> tuple[User, str] | None:
        row = self.db.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            [username],
        ).fetchone()
        if row is None:
            return None
        return User(id=row["id"], username=row["username"]), row["password_hash"]

    def get_user(self, user_id: str) -> User | None:
        row = self.db.execute(
            "SELECT id, username FROM users WHERE id = ?", [user_id],
        ).fetchone()
        if row is None:
            return None
        return User(id=row["id"], username=row["username"])

    def authenticate(self, *, username: str, password: str) -> User | None:
        """Constant-ish time auth: always hash the attempted password.

        Returns the authenticated user on success, or None on failure.
        """
        existing = self.find_by_username(username)
        if existing is None:
            # Hash something to equalize timing against the user-exists path.
            self._verify(self._hash("dummy-for-timing"), password)
            return None
        user, stored_hash = existing
        if self._verify(stored_hash, password):
            return user
        return None

    # ---- auth sessions --------------------------------------------------

    def create_session(self, user_id: str) -> tuple[str, float]:
        """Issue a new session token. Returns (token, expires_at)."""
        token = secrets.token_urlsafe(32)
        now = time.time()
        expires_at = now + SESSION_TTL_SECONDS
        self.db.execute(
            "INSERT INTO auth_sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            [token, user_id, now, expires_at],
        )
        self.db.commit()
        return token, expires_at

    def resolve_session(self, token: str) -> User | None:
        """Resolve a session token to a user; slides the expiry on hit."""
        now = time.time()
        row = self.db.execute(
            "SELECT token, user_id, expires_at FROM auth_sessions WHERE token = ?",
            [token],
        ).fetchone()
        if row is None or row["expires_at"] < now:
            if row is not None:
                # Clean up the expired row.
                self.db.execute(
                    "DELETE FROM auth_sessions WHERE token = ?", [token]
                )
                self.db.commit()
            return None
        # Slide expiry (within the TTL).
        new_expiry = now + SESSION_TTL_SECONDS
        self.db.execute(
            "UPDATE auth_sessions SET expires_at = ? WHERE token = ?",
            [new_expiry, token],
        )
        self.db.commit()
        return self.get_user(row["user_id"])

    def delete_session(self, token: str) -> None:
        self.db.execute("DELETE FROM auth_sessions WHERE token = ?", [token])
        self.db.commit()


# ---------------------------------------------------------------------------
# Dev bypass
# ---------------------------------------------------------------------------


def _dev_bypass_enabled() -> bool:
    if os.environ.get("ENV", "").lower() == "production":
        return False
    return os.environ.get("APEX_DEV_BYPASS_AUTH", "").lower() in {"1", "true", "yes"}


def dev_bypass_user(store: AuthStore) -> User:
    """Ensure a dev user exists and return it (dev bypass only)."""
    existing = store.find_by_username("dev")
    if existing is not None:
        return existing[0]
    return store.create_user(username="dev", password="dev-bypass-password")
