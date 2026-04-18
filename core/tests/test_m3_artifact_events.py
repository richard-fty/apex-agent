"""M3 tests — tools emit artifact events through ToolContext."""

from __future__ import annotations

import pytest

from agent.artifacts import ArtifactKind, ArtifactSpec, FilesystemArtifactStore
from agent.events import (
    ArtifactCreated,
    ArtifactFinalized,
    ArtifactPatch,
    ArtifactPatchOp,
    InMemoryEventBus,
)
from agent.runtime.tool_context import (
    ToolContext,
    emit_artifact_append,
    emit_artifact_created,
    emit_artifact_finalized,
    emit_artifact_replace,
    get_tool_context,
    tool_context_scope,
)


class TestToolContextScope:
    def test_context_not_set_outside_scope(self):
        assert get_tool_context() is None

    @pytest.mark.asyncio
    async def test_scope_sets_and_resets(self, tmp_path):
        bus = InMemoryEventBus()
        store = FilesystemArtifactStore(root=tmp_path)
        ctx = ToolContext(session_id="s1", turn_id="t1", event_bus=bus, artifact_store=store)

        with tool_context_scope(ctx):
            assert get_tool_context() is ctx
        assert get_tool_context() is None


class TestArtifactEmissionHelpers:
    @pytest.mark.asyncio
    async def test_create_append_finalize_emits_events_and_persists(self, tmp_path):
        bus = InMemoryEventBus()
        store = FilesystemArtifactStore(root=tmp_path)
        ctx = ToolContext(session_id="s1", turn_id="t1", event_bus=bus, artifact_store=store)

        with tool_context_scope(ctx):
            artifact_id = await emit_artifact_created(
                spec=ArtifactSpec(
                    kind=ArtifactKind.MARKDOWN,
                    name="report.md",
                ),
            )
            assert artifact_id is not None
            await emit_artifact_append(artifact_id, "# Hello\n")
            await emit_artifact_append(artifact_id, "world")
            await emit_artifact_finalized(artifact_id)

        # Event bus captured four events in order
        events = bus._buffered("s1")
        types = [type(e).__name__ for e in events]
        assert types == [
            "ArtifactCreated",
            "ArtifactPatch",
            "ArtifactPatch",
            "ArtifactFinalized",
        ]
        assert events[0].artifact_id == artifact_id
        assert events[1].op == ArtifactPatchOp.APPEND
        assert events[1].text == "# Hello\n"
        assert events[3].size == len(b"# Hello\nworld")

        # Content persisted on disk via the store.
        assert await store.read_all("s1", artifact_id) == b"# Hello\nworld"

    @pytest.mark.asyncio
    async def test_replace_op_fires_patch_with_content(self, tmp_path):
        bus = InMemoryEventBus()
        store = FilesystemArtifactStore(root=tmp_path)
        ctx = ToolContext(session_id="s1", turn_id="t1", event_bus=bus, artifact_store=store)

        with tool_context_scope(ctx):
            aid = await emit_artifact_created(
                spec=ArtifactSpec(kind=ArtifactKind.JSON, name="cfg.json"),
            )
            assert aid is not None
            await emit_artifact_replace(aid, '{"a":1}')

        events = bus._buffered("s1")
        patches = [e for e in events if isinstance(e, ArtifactPatch)]
        assert len(patches) == 1
        assert patches[0].op == ArtifactPatchOp.REPLACE
        assert patches[0].content == '{"a":1}'

    @pytest.mark.asyncio
    async def test_helpers_noop_without_context(self, tmp_path):
        # No context installed: emit helpers return silently.
        assert await emit_artifact_created(spec=ArtifactSpec(kind=ArtifactKind.TEXT, name="x")) is None
        # Should not raise:
        await emit_artifact_append("nonexistent", "x")
        await emit_artifact_finalized("nonexistent")


class TestWriteFileEmitsArtifact:
    @pytest.mark.asyncio
    async def test_write_file_markdown_creates_artifact_events(self, tmp_path, monkeypatch):
        """WriteFileTool emits artifact_created + replace + finalized on write."""
        from tools.filesystem import WriteFileTool

        bus = InMemoryEventBus()
        store = FilesystemArtifactStore(root=tmp_path / "artifacts")
        ctx = ToolContext(session_id="sess", turn_id="t", event_bus=bus, artifact_store=store)

        target = tmp_path / "report.md"
        tool = WriteFileTool()
        with tool_context_scope(ctx):
            msg = await tool.execute(path=str(target), content="# Hi\n")
        assert "Written" in msg

        events = bus._buffered("sess")
        kinds = [type(e).__name__ for e in events]
        assert "ArtifactCreated" in kinds
        assert "ArtifactPatch" in kinds
        assert "ArtifactFinalized" in kinds

        # Metadata reflects markdown kind.
        created = next(e for e in events if isinstance(e, ArtifactCreated))
        assert created.kind == ArtifactKind.MARKDOWN
        assert created.name == "report.md"
