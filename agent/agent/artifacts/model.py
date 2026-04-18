"""Artifact data models."""

from __future__ import annotations

import time

from pydantic import BaseModel, Field

from agent.events.schema import ArtifactKind


class ArtifactSpec(BaseModel):
    """Descriptor used to create a new artifact."""

    kind: ArtifactKind
    name: str
    language: str | None = None  # for ArtifactKind.CODE
    mime: str | None = None  # for ArtifactKind.IMAGE / PDF / FILE
    description: str | None = None


class Artifact(BaseModel):
    """A stored artifact — metadata only; content is fetched via store.read."""

    id: str
    session_id: str
    spec: ArtifactSpec
    created_at: float = Field(default_factory=time.time)
    finalized_at: float | None = None
    size: int = 0
    checksum: str | None = None
