"""M1 contract tests — event schema, event bus, artifact store, session store."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from agent.artifacts import ArtifactKind, ArtifactSpec, FilesystemArtifactStore
from agent.events import (
    ApprovalRequested,
    ArtifactCreated,
    ArtifactPatch,
    ArtifactPatchOp,
    AssistantToken,
    InMemoryEventBus,
    StreamEnd,
    ToolStarted,
    event_adapter,
)
from agent.session.archive import SessionArchive
from agent.session.store import SessionPatch, SessionSpec, SqliteSessionStore


# ---------------------------------------------------------------------------
# Event schema
# ---------------------------------------------------------------------------


class TestEventSchema:
    def test_event_roundtrips_through_json(self):
        events = [
            ToolStarted(session_id="s1", turn_id="t1", step=0, name="ls"),
            ArtifactCreated(
                session_id="s1",
                artifact_id="a1",
                kind=ArtifactKind.MARKDOWN,
                name="report.md",
            ),
            ArtifactPatch(
                session_id="s1",
                artifact_id="a1",
                op=ArtifactPatchOp.APPEND,
                text="hello",
            ),
            StreamEnd(session_id="s1", turn_id="t1", final_state="completed"),
        ]
        for e in events:
            parsed = event_adapter.validate_json(e.model_dump_json())
            assert type(parsed) is type(e)
            assert parsed.model_dump() == e.model_dump()

    def test_discriminator_rejects_unknown_type(self):
        with pytest.raises(Exception):
            event_adapter.validate_python({
                "type": "not_a_real_event",
                "session_id": "s1",
            })

    def test_approval_requested_has_step(self):
        # ApprovalRequested must carry enough context to show in UI
        e = ApprovalRequested(
            session_id="s1", turn_id="t1", step=3,
            tool_name="sandbox_exec", reason="network",
        )
        assert e.step == 3
        assert e.tool_name == "sandbox_exec"


# ---------------------------------------------------------------------------
# Event bus
# ---------------------------------------------------------------------------


class TestInMemoryEventBus:
    @pytest.mark.asyncio
    async def test_subscriber_receives_live_events_and_terminates_on_stream_end(self):
        bus = InMemoryEventBus()

        received = []

        async def consumer():
            async for e in bus.subscribe("s1"):
                received.append(e)

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.01)

        for i in range(3):
            await bus.publish(
                "s1",
                AssistantToken(session_id="s1", turn_id="t1", seq=i + 1, text=f"tok{i}"),
            )
        await bus.publish(
            "s1",
            StreamEnd(session_id="s1", turn_id="t1", seq=4, final_state="completed"),
        )

        await asyncio.wait_for(task, timeout=1.0)
        assert len(received) == 4
        assert isinstance(received[-1], StreamEnd)

    @pytest.mark.asyncio
    async def test_replay_from_since_seq(self):
        bus = InMemoryEventBus()
        # Publish a few events with nobody subscribed; the ring buffer keeps them.
        for i in range(1, 5):
            await bus.publish(
                "s1",
                AssistantToken(session_id="s1", turn_id="t1", seq=i, text=str(i)),
            )
        await bus.publish(
            "s1",
            StreamEnd(session_id="s1", turn_id="t1", seq=5, final_state="completed"),
        )

        received = []
        async for e in bus.subscribe("s1", since_seq=2):
            received.append(e)
        assert [e.seq for e in received] == [3, 4, 5]
        assert isinstance(received[-1], StreamEnd)

    @pytest.mark.asyncio
    async def test_multiple_subscribers_fan_out(self):
        bus = InMemoryEventBus()
        got_a: list = []
        got_b: list = []

        async def a():
            async for e in bus.subscribe("s1"):
                got_a.append(e)

        async def b():
            async for e in bus.subscribe("s1"):
                got_b.append(e)

        ta = asyncio.create_task(a())
        tb = asyncio.create_task(b())
        await asyncio.sleep(0.01)
        assert bus._subscriber_count("s1") == 2

        await bus.publish(
            "s1",
            AssistantToken(session_id="s1", turn_id="t1", seq=1, text="hello"),
        )
        await bus.publish(
            "s1",
            StreamEnd(session_id="s1", turn_id="t1", seq=2, final_state="completed"),
        )
        await asyncio.wait_for(asyncio.gather(ta, tb), timeout=1.0)
        assert len(got_a) == 2 and len(got_b) == 2
        assert bus._subscriber_count("s1") == 0

    @pytest.mark.asyncio
    async def test_close_session_disconnects_subscribers(self):
        bus = InMemoryEventBus()
        got: list = []

        async def consumer():
            async for e in bus.subscribe("s1"):
                got.append(e)

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.01)
        await bus.close_session("s1")
        await asyncio.wait_for(task, timeout=1.0)
        assert got == []


# ---------------------------------------------------------------------------
# Artifact store
# ---------------------------------------------------------------------------


class TestFilesystemArtifactStore:
    @pytest.mark.asyncio
    async def test_create_append_finalize_flow(self, tmp_path: Path):
        store = FilesystemArtifactStore(root=tmp_path)
        art = await store.create(
            "sess", ArtifactSpec(kind=ArtifactKind.MARKDOWN, name="r.md"),
        )
        assert art.finalized_at is None

        await store.append("sess", art.id, b"hello ")
        await store.append("sess", art.id, b"world")
        final = await store.finalize("sess", art.id)
        assert final.size == len(b"hello world")
        assert final.checksum is not None
        assert final.finalized_at is not None

        assert await store.read_all("sess", art.id) == b"hello world"

    @pytest.mark.asyncio
    async def test_cannot_modify_after_finalize(self, tmp_path: Path):
        store = FilesystemArtifactStore(root=tmp_path)
        art = await store.create("sess", ArtifactSpec(kind=ArtifactKind.TEXT, name="f"))
        await store.append("sess", art.id, b"x")
        await store.finalize("sess", art.id)
        with pytest.raises(RuntimeError):
            await store.append("sess", art.id, b"y")
        with pytest.raises(RuntimeError):
            await store.replace("sess", art.id, b"z")

    @pytest.mark.asyncio
    async def test_replace_swaps_full_content(self, tmp_path: Path):
        store = FilesystemArtifactStore(root=tmp_path)
        art = await store.create("sess", ArtifactSpec(kind=ArtifactKind.JSON, name="o"))
        await store.append("sess", art.id, b'{"a":1}')
        await store.replace("sess", art.id, b'{"b":2}')
        assert await store.read_all("sess", art.id) == b'{"b":2}'

    @pytest.mark.asyncio
    async def test_list_for_session(self, tmp_path: Path):
        store = FilesystemArtifactStore(root=tmp_path)
        a1 = await store.create("sess", ArtifactSpec(kind=ArtifactKind.TEXT, name="1"))
        a2 = await store.create("sess", ArtifactSpec(kind=ArtifactKind.TEXT, name="2"))
        listed = await store.list_for_session("sess")
        ids = {a.id for a in listed}
        assert ids == {a1.id, a2.id}

    @pytest.mark.asyncio
    async def test_delete_removes_content_and_metadata(self, tmp_path: Path):
        store = FilesystemArtifactStore(root=tmp_path)
        art = await store.create("sess", ArtifactSpec(kind=ArtifactKind.TEXT, name="g"))
        await store.append("sess", art.id, b"bye")
        await store.delete("sess", art.id)
        with pytest.raises(FileNotFoundError):
            await store.metadata("sess", art.id)


# ---------------------------------------------------------------------------
# Session store
# ---------------------------------------------------------------------------


class TestSqliteSessionStore:
    @pytest.mark.asyncio
    async def test_create_preserves_owner(self, tmp_path: Path):
        archive = SessionArchive(db_path=str(tmp_path / "a.db"))
        store = SqliteSessionStore(archive=archive)
        s = await store.create(SessionSpec(model="m", owner_user_id="alice"))
        assert s.owner_user_id == "alice"
        again = await store.get(s.id)
        assert again is not None and again.owner_user_id == "alice"

    @pytest.mark.asyncio
    async def test_update_preserves_owner(self, tmp_path: Path):
        archive = SessionArchive(db_path=str(tmp_path / "a.db"))
        store = SqliteSessionStore(archive=archive)
        s = await store.create(SessionSpec(model="m", owner_user_id="alice"))
        updated = await store.update(s.id, SessionPatch(state="running"))
        assert updated.state == "running"
        assert updated.owner_user_id == "alice"

    @pytest.mark.asyncio
    async def test_list_for_user_filters_by_owner(self, tmp_path: Path):
        archive = SessionArchive(db_path=str(tmp_path / "a.db"))
        store = SqliteSessionStore(archive=archive)
        await store.create(SessionSpec(model="m", owner_user_id="alice"))
        await store.create(SessionSpec(model="m", owner_user_id="alice"))
        await store.create(SessionSpec(model="m", owner_user_id="bob"))
        assert len(await store.list_for_user("alice")) == 2
        assert len(await store.list_for_user("bob")) == 1
        assert len(await store.list_for_user("eve")) == 0

    @pytest.mark.asyncio
    async def test_delete_session_removes_events(self, tmp_path: Path):
        archive = SessionArchive(db_path=str(tmp_path / "a.db"))
        store = SqliteSessionStore(archive=archive)
        s = await store.create(SessionSpec(model="m", owner_user_id="alice"))
        await store.append_event(s.id, "foo", {"x": 1})
        await store.delete(s.id)
        assert await store.get(s.id) is None
        assert archive.get_events(s.id) == []

    @pytest.mark.asyncio
    async def test_missing_session_get_returns_none(self, tmp_path: Path):
        archive = SessionArchive(db_path=str(tmp_path / "a.db"))
        store = SqliteSessionStore(archive=archive)
        assert await store.get("does-not-exist") is None
