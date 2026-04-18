"""Access control and human-in-the-loop approval for agent tool use."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.core.models import (
    PermissionDecision,
    PendingApproval,
    ToolCall,
    ToolDef,
)
from agent.policy.approval_manager import ApprovalManager
from agent.policy.permission_policy import PermissionPolicyEngine
from agent.policy.policy_models import AccessPolicy, PRESET_POLICIES, get_policy


@dataclass
class AccessController:
    """Evaluate permission decisions and manage resumable approvals."""

    policy: AccessPolicy
    call_counts: dict[str, int] = field(default_factory=dict)
    approval_manager: ApprovalManager = field(default_factory=ApprovalManager)
    permission_engine: PermissionPolicyEngine = field(default_factory=PermissionPolicyEngine)

    def __post_init__(self) -> None:
        self.approval_manager.mode_scope = self.policy.mode

    def evaluate(self, tool_call: ToolCall, tool_def: ToolDef) -> PermissionDecision:
        """Return a structured allow/ask/deny decision for a tool call."""
        return self.permission_engine.evaluate(
            policy=self.policy,
            approval_rules=self.approval_manager.approval_rules,
            call_counts=self.call_counts,
            denied_calls=self.approval_manager.denied_calls,
            tool_call=tool_call,
            tool_def=tool_def,
        )

    def create_pending(self, tool_call: ToolCall, decision: PermissionDecision) -> PendingApproval:
        return self.approval_manager.create_pending(tool_call, decision)

    def resolve_pending(self, action: str) -> PermissionDecision | None:
        return self.approval_manager.resolve_pending(action)

    def record_allow(self, tool_name: str) -> None:
        self.call_counts[tool_name] = self.call_counts.get(tool_name, 0) + 1

    def summary(self) -> dict[str, Any]:
        return {
            "mode": self.policy.mode.value,
            "total_calls": sum(self.call_counts.values()),
            "call_counts": dict(self.call_counts),
            **self.approval_manager.summary(),
        }

    @property
    def pending(self) -> PendingApproval | None:
        return self.approval_manager.pending

    @property
    def approval_rules(self) -> list[Any]:
        return self.approval_manager.approval_rules

    @property
    def denied_calls(self) -> list[dict[str, Any]]:
        return self.approval_manager.denied_calls
