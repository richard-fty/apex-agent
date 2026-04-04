"""Manage pending approvals and session-scoped approval rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.models import (
    ApprovalRule,
    PermissionAction,
    PermissionDecision,
    PendingApproval,
    ToolCall,
)


@dataclass
class ApprovalManager:
    """Store pending approval state plus session approval rules."""

    approval_rules: list[ApprovalRule] = field(default_factory=list)
    denied_calls: list[dict[str, Any]] = field(default_factory=list)
    pending: PendingApproval | None = None
    mode_scope: Any = None

    def create_pending(self, tool_call: ToolCall, decision: PermissionDecision) -> PendingApproval:
        self.pending = PendingApproval(tool_call=tool_call, decision=decision)
        return self.pending

    def resolve_pending(self, action: str) -> PermissionDecision | None:
        if self.pending is None:
            return None

        tool_call = self.pending.tool_call
        if action == "approve_once":
            decision = PermissionDecision(
                action=PermissionAction.ALLOW,
                reason="Approved once by user",
                rule_source="user.approve_once",
            )
        elif action == "approve_session":
            self.approval_rules.append(self._rule_from_tool_call(tool_call, PermissionAction.ALLOW))
            decision = PermissionDecision(
                action=PermissionAction.ALLOW,
                reason="Approved for this session",
                rule_source="user.approve_session",
            )
        elif action == "deny_session":
            self.approval_rules.append(self._rule_from_tool_call(tool_call, PermissionAction.DENY))
            decision = PermissionDecision(
                action=PermissionAction.DENY,
                reason="Denied for this session",
                rule_source="user.deny_session",
            )
        else:
            decision = PermissionDecision(
                action=PermissionAction.DENY,
                reason="Denied by user",
                rule_source="user.deny",
            )
            self.denied_calls.append({"tool": tool_call.name, "reason": decision.reason})

        self.pending = None
        return decision

    def summary(self) -> dict[str, Any]:
        return {
            "approval_rules": [rule.model_dump() for rule in self.approval_rules],
            "pending": self.pending.model_dump() if self.pending else None,
            "denied_count": len(self.denied_calls),
            "denied_calls": self.denied_calls,
        }

    def _rule_from_tool_call(self, tool_call: ToolCall, action: PermissionAction) -> ApprovalRule:
        command = tool_call.arguments.get("command")
        path = tool_call.arguments.get("path")
        return ApprovalRule(
            tool_name=tool_call.name,
            action=action,
            mode_scope=self.mode_scope,
            command_prefix=str(command) if command else None,
            path_prefix=str(path) if path else None,
        )
