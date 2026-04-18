"""Artifact storage backends.

MVP: filesystem-backed under `results/artifacts/{session_id}/{artifact_id}`
with a `.meta.json` sidecar for metadata. Content is streamed as raw bytes.

Later: `S3ArtifactStore` with signed URLs; the `ArtifactStore` protocol stays
unchanged so callers don't care where content lives.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import AsyncIterator, Protocol

from agent.artifacts.model import Artifact, ArtifactSpec


class ArtifactStore(Protocol):
    """Session-scoped artifact storage."""

    async def create(self, session_id: str, spec: ArtifactSpec) -> Artifact:
        ...

    async def append(self, session_id: str, artifact_id: str, chunk: bytes) -> None:
        ...

    async def replace(self, session_id: str, artifact_id: str, content: bytes) -> None:
        ...

    async def finalize(self, session_id: str, artifact_id: str) -> Artifact:
        ...

    async def read(self, session_id: str, artifact_id: str) -> AsyncIterator[bytes]:
        ...

    async def read_all(self, session_id: str, artifact_id: str) -> bytes:
        ...

    async def metadata(self, session_id: str, artifact_id: str) -> Artifact:
        ...

    async def list_for_session(self, session_id: str) -> list[Artifact]:
        ...

    async def delete(self, session_id: str, artifact_id: str) -> None:
        ...


class FilesystemArtifactStore:
    """Local-disk artifact store.

    Layout:
        <root>/<session_id>/<artifact_id>         # raw content
        <root>/<session_id>/<artifact_id>.meta.json
    """

    _READ_CHUNK = 64 * 1024

    def __init__(self, root: str | Path = "results/artifacts") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, asyncio.Lock] = {}

    # ---- paths -------------------------------------------------------------

    def _session_dir(self, session_id: str) -> Path:
        return self.root / session_id

    def _content_path(self, session_id: str, artifact_id: str) -> Path:
        return self._session_dir(session_id) / artifact_id

    def _meta_path(self, session_id: str, artifact_id: str) -> Path:
        return self._session_dir(session_id) / f"{artifact_id}.meta.json"

    def _lock(self, artifact_id: str) -> asyncio.Lock:
        lock = self._locks.get(artifact_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[artifact_id] = lock
        return lock

    # ---- public API --------------------------------------------------------

    async def create(self, session_id: str, spec: ArtifactSpec) -> Artifact:
        artifact_id = uuid.uuid4().hex
        session_dir = self._session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        artifact = Artifact(
            id=artifact_id,
            session_id=session_id,
            spec=spec,
            created_at=time.time(),
        )
        # Create empty content file and metadata sidecar.
        self._content_path(session_id, artifact_id).touch()
        self._write_meta(artifact)
        return artifact

    async def append(self, session_id: str, artifact_id: str, chunk: bytes) -> None:
        async with self._lock(artifact_id):
            path = self._content_path(session_id, artifact_id)
            self._require_open(session_id, artifact_id)
            with path.open("ab") as f:
                f.write(chunk)

    async def replace(self, session_id: str, artifact_id: str, content: bytes) -> None:
        async with self._lock(artifact_id):
            self._require_open(session_id, artifact_id)
            self._content_path(session_id, artifact_id).write_bytes(content)

    async def finalize(self, session_id: str, artifact_id: str) -> Artifact:
        async with self._lock(artifact_id):
            path = self._content_path(session_id, artifact_id)
            data = path.read_bytes()
            artifact = self._read_meta(session_id, artifact_id)
            artifact.size = len(data)
            artifact.checksum = hashlib.sha256(data).hexdigest()
            artifact.finalized_at = time.time()
            self._write_meta(artifact)
            return artifact

    async def read(self, session_id: str, artifact_id: str) -> AsyncIterator[bytes]:
        path = self._content_path(session_id, artifact_id)
        if not path.exists():
            raise FileNotFoundError(f"artifact {artifact_id} not found")
        # Simple sync read in chunks; good enough for MVP. Swap for aiofiles later.
        async def _iter() -> AsyncIterator[bytes]:
            with path.open("rb") as f:
                while True:
                    chunk = f.read(self._READ_CHUNK)
                    if not chunk:
                        return
                    yield chunk
        return _iter()

    async def read_all(self, session_id: str, artifact_id: str) -> bytes:
        path = self._content_path(session_id, artifact_id)
        if not path.exists():
            raise FileNotFoundError(f"artifact {artifact_id} not found")
        return path.read_bytes()

    async def metadata(self, session_id: str, artifact_id: str) -> Artifact:
        return self._read_meta(session_id, artifact_id)

    async def list_for_session(self, session_id: str) -> list[Artifact]:
        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            return []
        out: list[Artifact] = []
        for meta in sorted(session_dir.glob("*.meta.json")):
            artifact_id = meta.stem.removesuffix(".meta")
            try:
                out.append(self._read_meta(session_id, artifact_id))
            except FileNotFoundError:
                continue
        out.sort(key=lambda a: a.created_at)
        return out

    async def delete(self, session_id: str, artifact_id: str) -> None:
        async with self._lock(artifact_id):
            for p in (
                self._content_path(session_id, artifact_id),
                self._meta_path(session_id, artifact_id),
            ):
                if p.exists():
                    p.unlink()
        self._locks.pop(artifact_id, None)

    # ---- internals ---------------------------------------------------------

    def _require_open(self, session_id: str, artifact_id: str) -> None:
        meta = self._read_meta(session_id, artifact_id)
        if meta.finalized_at is not None:
            raise RuntimeError(
                f"artifact {artifact_id} is finalized; cannot append/replace"
            )

    def _write_meta(self, artifact: Artifact) -> None:
        path = self._meta_path(artifact.session_id, artifact.id)
        path.write_text(artifact.model_dump_json(indent=2))

    def _read_meta(self, session_id: str, artifact_id: str) -> Artifact:
        path = self._meta_path(session_id, artifact_id)
        if not path.exists():
            raise FileNotFoundError(f"artifact {artifact_id} metadata missing")
        return Artifact.model_validate_json(path.read_text())
