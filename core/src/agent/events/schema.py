"""Typed agent events.

Every runtime-emitted event is a pydantic model with a `type` discriminator.
The `AgentEvent` union is a tagged union consumers can parse from JSON via
`event_adapter.validate_json(...)` and serialize via `model_dump_json()`.

Design notes:

- `seq` is the monotonic per-session sequence number. The runtime leaves it
  unset on publish; the `SessionStore.append_event` call assigns it.
- `turn_id` is optional: lifecycle events like `session_created` and control
  events like `stream_end` are session-level, not turn-level.
- `StreamEnd` is the sentinel consumers use to close their subscription.
  It is emitted after every terminal transition (turn_finished, error,
  approval_requested that pauses the turn). Consumers must stop on this
  event rather than inferring termination from session state.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter

from agent.core.models import TodoStatus, TokenUsage


# ---------------------------------------------------------------------------
# Shared enums and value objects
# ---------------------------------------------------------------------------


class ArtifactKind(str, Enum):
    CODE = "code"
    MARKDOWN = "markdown"
    TEXT = "text"
    JSON = "json"
    WEALTH_SNAPSHOT = "wealth_snapshot"
    PATH_COMPARISON = "path_comparison"
    ACTION_CHECKLIST = "action_checklist"
    IMAGE = "image"
    PDF = "pdf"
    FILE = "file"
    TERMINAL_LOG = "terminal_log"
    PLAN = "plan"
    APP_PREVIEW = "app_preview"


class ArtifactPatchOp(str, Enum):
    APPEND = "append"
    REPLACE = "replace"


class TodoItem(BaseModel):
    id: str
    text: str
    status: TodoStatus = "pending"


PlanStep = TodoItem


class SearchResultCard(BaseModel):
    title: str
    url: str
    snippet: str = ""
    source: str | None = None
    timestamp: str | None = None


# ---------------------------------------------------------------------------
# Base event
# ---------------------------------------------------------------------------


class AgentEventBase(BaseModel):
    """Fields common to every event."""

    session_id: str
    turn_id: str | None = None
    seq: int = 0  # Assigned by SessionStore.append_event; 0 means "unassigned"
    timestamp: float = Field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Lifecycle events
# ---------------------------------------------------------------------------


class SessionCreated(AgentEventBase):
    type: Literal["session_created"] = "session_created"
    model: str
    owner_user_id: str | None = None


class TurnStarted(AgentEventBase):
    type: Literal["turn_started"] = "turn_started"
    user_input: str


class TurnFinished(AgentEventBase):
    type: Literal["turn_finished"] = "turn_finished"
    content: str = ""


class StreamEnd(AgentEventBase):
    """Sentinel: consumers close their subscription on this event.

    Emitted after every terminal transition (turn_finished, error,
    or approval_requested that pauses the turn). Carries the final state
    so consumers can render appropriate UI (completed vs waiting_approval).
    """

    type: Literal["stream_end"] = "stream_end"
    final_state: Literal[
        "completed", "waiting_approval", "failed", "cancelled"
    ]
    reason: str | None = None


class ErrorEvent(AgentEventBase):
    type: Literal["error"] = "error"
    message: str


# ---------------------------------------------------------------------------
# Reasoning events
# ---------------------------------------------------------------------------


class AssistantToken(AgentEventBase):
    type: Literal["assistant_token"] = "assistant_token"
    text: str


class AssistantMessage(AgentEventBase):
    type: Literal["assistant_message"] = "assistant_message"
    content: str


class AssistantNote(AgentEventBase):
    """Inline thinking text emitted between tool calls (not the final message)."""

    type: Literal["assistant_note"] = "assistant_note"
    text: str


class SkillAutoLoaded(AgentEventBase):
    type: Literal["skill_auto_loaded"] = "skill_auto_loaded"
    skill_name: str


class PlanUpdated(AgentEventBase):
    type: Literal["plan_updated"] = "plan_updated"
    steps: list[PlanStep]


class EducationDisclaimer(AgentEventBase):
    type: Literal["education_disclaimer"] = "education_disclaimer"
    message: str
    scope: Literal["education"] = "education"


# ---------------------------------------------------------------------------
# Tool events
# ---------------------------------------------------------------------------


class ToolStarted(AgentEventBase):
    type: Literal["tool_started"] = "tool_started"
    step: int
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolFinished(AgentEventBase):
    type: Literal["tool_finished"] = "tool_finished"
    step: int
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    success: bool
    duration_ms: float
    content: str = ""
    search_results: list[SearchResultCard] = Field(default_factory=list)


class ToolDenied(AgentEventBase):
    type: Literal["tool_denied"] = "tool_denied"
    name: str
    reason: str


class ApprovalRequested(AgentEventBase):
    type: Literal["approval_requested"] = "approval_requested"
    step: int
    tool_name: str
    reason: str


class ApprovalResolved(AgentEventBase):
    type: Literal["approval_resolved"] = "approval_resolved"
    tool_name: str
    action: Literal["approve_once", "approve_session", "deny", "deny_session"]


# ---------------------------------------------------------------------------
# Artifact events
# ---------------------------------------------------------------------------


class ArtifactCreated(AgentEventBase):
    type: Literal["artifact_created"] = "artifact_created"
    artifact_id: str
    kind: ArtifactKind
    name: str
    language: str | None = None
    mime: str | None = None
    description: str | None = None


class ArtifactPatch(AgentEventBase):
    """Incremental artifact content.

    For append-only kinds (markdown streaming, terminal_log, code being
    written), use `op=APPEND` with `text`. For kinds that want a full replace
    (JSON object being edited, plan snapshot), use `op=REPLACE` with `content`.
    The server may coalesce several APPEND patches for the same artifact into
    one event to avoid flooding the stream.
    """

    type: Literal["artifact_patch"] = "artifact_patch"
    artifact_id: str
    op: ArtifactPatchOp
    text: str | None = None  # APPEND payload
    content: str | None = None  # REPLACE payload (full new content)


class ArtifactFinalized(AgentEventBase):
    type: Literal["artifact_finalized"] = "artifact_finalized"
    artifact_id: str
    size: int
    checksum: str | None = None


class ArtifactDeleted(AgentEventBase):
    type: Literal["artifact_deleted"] = "artifact_deleted"
    artifact_id: str


# ---------------------------------------------------------------------------
# Sandbox events
# ---------------------------------------------------------------------------


class SandboxExecStarted(AgentEventBase):
    type: Literal["sandbox_exec_started"] = "sandbox_exec_started"
    exec_id: str
    cmd: str
    cwd: str | None = None


class SandboxExecOutput(AgentEventBase):
    type: Literal["sandbox_exec_output"] = "sandbox_exec_output"
    exec_id: str
    stream: Literal["stdout", "stderr"]
    text: str


class SandboxExecFinished(AgentEventBase):
    type: Literal["sandbox_exec_finished"] = "sandbox_exec_finished"
    exec_id: str
    exit_code: int
    duration_ms: float


# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------


class UsageEvent(AgentEventBase):
    type: Literal["usage"] = "usage"
    step: int
    usage: TokenUsage
    duration_ms: float


# ---------------------------------------------------------------------------
# Discriminated union
# ---------------------------------------------------------------------------


AgentEvent = Annotated[
    Union[
        SessionCreated,
        TurnStarted,
        TurnFinished,
        StreamEnd,
        ErrorEvent,
        AssistantToken,
        AssistantMessage,
        AssistantNote,
        SkillAutoLoaded,
        PlanUpdated,
        EducationDisclaimer,
        ToolStarted,
        ToolFinished,
        ToolDenied,
        ApprovalRequested,
        ApprovalResolved,
        ArtifactCreated,
        ArtifactPatch,
        ArtifactFinalized,
        ArtifactDeleted,
        SandboxExecStarted,
        SandboxExecOutput,
        SandboxExecFinished,
        UsageEvent,
    ],
    Field(discriminator="type"),
]


event_adapter: TypeAdapter[AgentEvent] = TypeAdapter(AgentEvent)
"""Parse any AgentEvent from JSON or dict via `event_adapter.validate_*`."""
