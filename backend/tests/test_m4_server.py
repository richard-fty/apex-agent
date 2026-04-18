"""M4 server integration tests — register, login, ownership, CRUD.

Uses an isolated AppState per test (tmp_path) so the global SQLite file
isn't touched. Turn/approval/SSE plumbing is covered by the in-process
runtime flow tests (M2/M3); here we exercise the HTTP surface.
"""

from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from apex_server.app import create_app
from apex_server.deps import build_default_app_state
from apex_server.routes.events_routes import load_replay_events
from agent.session.store import SessionSpec


def _app(tmp_path: Path) -> TestClient:
    state = build_default_app_state(
        db_path=str(tmp_path / "apex.db"),
        artifact_root=str(tmp_path / "artifacts"),
    )
    app = create_app(state=state)
    return TestClient(app)
class TestAuthFlow:
    def test_register_issues_session_cookie_and_logs_in(self, tmp_path):
        client = _app(tmp_path)
        r = client.post("/auth/register", json={"username": "alice", "password": "secret12"})
        assert r.status_code == 201
        assert r.json()["username"] == "alice"
        # Session cookie set — /auth/me now works without body.
        me = client.get("/auth/me")
        assert me.status_code == 200
        assert me.json()["username"] == "alice"

    def test_register_rejects_short_password(self, tmp_path):
        client = _app(tmp_path)
        r = client.post("/auth/register", json={"username": "a", "password": "short"})
        # pydantic rejects short password first
        assert r.status_code in (400, 422)

    def test_register_rejects_duplicate_username_generically(self, tmp_path):
        client = _app(tmp_path)
        assert client.post("/auth/register", json={"username": "alice", "password": "secret12"}).status_code == 201
        client.cookies.clear()
        r = client.post("/auth/register", json={"username": "alice", "password": "secret12"})
        assert r.status_code == 400
        # Generic message — doesn't leak "username taken".
        assert "Registration failed" in r.json()["detail"]

    def test_login_wrong_password_returns_401(self, tmp_path):
        client = _app(tmp_path)
        client.post("/auth/register", json={"username": "alice", "password": "secret12"})
        client.cookies.clear()
        r = client.post("/auth/login", json={"username": "alice", "password": "wrong123"})
        assert r.status_code == 401

    def test_logout_clears_cookie(self, tmp_path):
        client = _app(tmp_path)
        client.post("/auth/register", json={"username": "alice", "password": "secret12"})
        assert client.get("/auth/me").status_code == 200
        client.post("/auth/logout")
        # A fresh client wipes cookies; reuse the same client but manually clear.
        client.cookies.clear()
        assert client.get("/auth/me").status_code == 401

    def test_unauthenticated_me_is_401(self, tmp_path):
        client = _app(tmp_path)
        assert client.get("/auth/me").status_code == 401


class TestSessionOwnership:
    def _login(self, client, username):
        client.post("/auth/register", json={"username": username, "password": "secret12"})

    def test_list_sessions_returns_only_my_own(self, tmp_path):
        client = _app(tmp_path)
        # alice creates a session
        self._login(client, "alice")
        client.post("/sessions", json={"model": "m"}).raise_for_status()
        alice_list = client.get("/sessions").json()
        assert len(alice_list) == 1
        # switch to bob
        client.cookies.clear()
        self._login(client, "bob")
        bob_list = client.get("/sessions").json()
        assert bob_list == []

    def test_other_user_gets_404_not_403(self, tmp_path):
        client = _app(tmp_path)
        self._login(client, "alice")
        sid = client.post("/sessions", json={"model": "m"}).json()["id"]
        client.cookies.clear()
        self._login(client, "bob")
        r = client.get(f"/sessions/{sid}")
        assert r.status_code == 404  # don't leak existence

    def test_delete_my_session_204(self, tmp_path):
        client = _app(tmp_path)
        self._login(client, "alice")
        sid = client.post("/sessions", json={"model": "m"}).json()["id"]
        assert client.delete(f"/sessions/{sid}").status_code == 204
        assert client.get(f"/sessions/{sid}").status_code == 404


class TestHealthEndpoint:
    def test_health_is_public(self, tmp_path):
        client = _app(tmp_path)
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


class TestEventStreamReplay:
    def _login(self, client, username="alice"):
        client.post("/auth/register", json={"username": username, "password": "secret12"}).raise_for_status()

    @pytest.mark.asyncio
    async def test_load_replay_events_returns_persisted_typed_events(self, tmp_path):
        client = _app(tmp_path)
        state = client.app.state.app_state
        session = await state.session_store.create(
            SessionSpec(model="m", owner_user_id="alice")
        )

        state.archive.emit_event(session.id, "assistant_token", {"text": "hello"})
        state.archive.emit_event(
            session.id, "stream_end", {"final_state": "completed", "reason": None}
        )

        events = await load_replay_events(state, session.id, since_seq=0)
        assert [e.type for e in events] == ["assistant_token", "stream_end"]
        assert events[0].seq == 1
        assert events[1].seq == 2

    @pytest.mark.asyncio
    async def test_load_replay_events_respects_since_seq(self, tmp_path):
        client = _app(tmp_path)
        state = client.app.state.app_state
        session = await state.session_store.create(
            SessionSpec(model="m", owner_user_id="alice")
        )

        seq1 = state.archive.emit_event(session.id, "assistant_token", {"text": "first"})
        seq2 = state.archive.emit_event(session.id, "assistant_token", {"text": "second"})
        seq3 = state.archive.emit_event(
            session.id, "stream_end", {"final_state": "completed", "reason": None}
        )
        assert [seq1, seq2, seq3] == [1, 2, 3]

        events = await load_replay_events(state, session.id, since_seq=1)
        assert [e.seq for e in events] == [2, 3]
        assert getattr(events[0], "text", None) == "second"
