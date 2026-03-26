"""Core data models for the agent system."""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Messages (OpenAI-compatible format — LiteLLM uses this)
# ---------------------------------------------------------------------------

class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolCallFunction(BaseModel):
    name: str
    arguments: str  # JSON string


class ToolCallMessage(BaseModel):
    id: str
    type: str = "function"
    function: ToolCallFunction


class Message(BaseModel):
    role: Role
    content: str | None = None
    tool_calls: list[ToolCallMessage] | None = None
    tool_call_id: str | None = None  # For role=tool responses
    name: str | None = None  # Tool name for role=tool

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for LiteLLM, dropping None fields."""
        d: dict[str, Any] = {"role": self.role.value}
        if self.content is not None:
            d["content"] = self.content
        if self.tool_calls is not None:
            d["tool_calls"] = [tc.model_dump() for tc in self.tool_calls]
        if self.tool_call_id is not None:
            d["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            d["name"] = self.name
        return d


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

class ToolParameter(BaseModel):
    name: str
    type: str  # "string", "number", "integer", "boolean", "object", "array"
    description: str
    required: bool = True
    enum: list[str] | None = None
    default: Any = None


class ToolDef(BaseModel):
    """Definition of a tool the agent can call."""
    name: str
    description: str
    parameters: list[ToolParameter]

    def to_openai_schema(self) -> dict[str, Any]:
        """Convert to OpenAI function-calling schema."""
        properties = {}
        required = []
        for p in self.parameters:
            prop: dict[str, Any] = {"type": p.type, "description": p.description}
            if p.enum:
                prop["enum"] = p.enum
            if p.default is not None:
                prop["default"] = p.default
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


# ---------------------------------------------------------------------------
# Tool call / result
# ---------------------------------------------------------------------------

class ToolCall(BaseModel):
    """A parsed tool call from the LLM response."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    arguments: dict[str, Any]


class ToolResult(BaseModel):
    """Result of executing a tool."""
    tool_call_id: str
    name: str
    content: str  # JSON string or plain text
    success: bool = True
    error: str | None = None


# ---------------------------------------------------------------------------
# Agent state
# ---------------------------------------------------------------------------

class AgentState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Events (for TUI / callbacks)
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    AGENT_START = "agent_start"
    LLM_CALL_START = "llm_call_start"
    LLM_STREAM_TOKEN = "llm_stream_token"
    LLM_CALL_END = "llm_call_end"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    CONTEXT_COMPACTION = "context_compaction"
    AGENT_END = "agent_end"
    AGENT_ERROR = "agent_error"


class AgentEvent(BaseModel):
    type: EventType
    step: int = 0
    timestamp: float = Field(default_factory=time.time)
    data: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Token usage
# ---------------------------------------------------------------------------

class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
