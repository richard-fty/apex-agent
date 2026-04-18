"""Artifact model and store — file-like outputs agents produce during a turn.

Artifacts are first-class entities the UI renders in a side panel. Tools
that produce file-like output (code runs, markdown reports, charts, terminal
logs) create an artifact via `ArtifactStore.create`, stream content with
`append`, then `finalize`. Each stage emits a matching event on the bus.
"""

from agent.artifacts.model import Artifact, ArtifactSpec
from agent.artifacts.store import ArtifactStore, FilesystemArtifactStore
from agent.events.schema import ArtifactKind, ArtifactPatchOp

__all__ = [
    "Artifact",
    "ArtifactKind",
    "ArtifactPatchOp",
    "ArtifactSpec",
    "ArtifactStore",
    "FilesystemArtifactStore",
]
