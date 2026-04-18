"""Permission policy engine for allow/ask/deny decisions."""

from __future__ import annotations

from pathlib import Path

from agent.core.models import (
    ApprovalRule,
    PermissionAction,
    PermissionDecision,
    PermissionMode,
    ToolCall,
    ToolDef,
)
from agent.policy.policy_models import AccessPolicy


class PermissionPolicyEngine:
    """Evaluate tool calls against policy, rules, and hard guards."""

    def evaluate(
        self,
        policy: AccessPolicy,
        approval_rules: list[ApprovalRule],
        call_counts: dict[str, int],
        denied_calls: list[dict[str, str]],
        tool_call: ToolCall,
        tool_def: ToolDef,
    ) -> PermissionDecision:
        name = tool_call.name

        if name in policy.blocked_tools:
            return self._deny(denied_calls, name, "Tool is blocked by access policy", "policy.blocked_tools")

        if policy.allowed_tools is not None and name not in policy.allowed_tools:
            return self._deny(denied_calls, name, "Tool is not in the allowed tools list", "policy.allowed_tools")

        limit = policy.tool_call_limits.get(name, 0)
        current = call_counts.get(name, 0)
        if limit > 0 and current >= limit:
            return self._deny(
                denied_calls,
                name,
                f"Tool call limit reached ({limit})",
                "policy.tool_call_limits",
            )

        hard_decision = self._evaluate_hard_guards(policy, denied_calls, tool_call, tool_def)
        if hard_decision is not None:
            return hard_decision

        rule_decision = self._evaluate_rules(policy, approval_rules, tool_call)
        if rule_decision is not None:
            return rule_decision

        mode_decision = self._evaluate_mode(policy, tool_call, tool_def)
        if mode_decision.action == PermissionAction.DENY:
            denied_calls.append({"tool": name, "reason": mode_decision.reason})

        return mode_decision

    def _evaluate_hard_guards(
        self,
        policy: AccessPolicy,
        denied_calls: list[dict[str, str]],
        tool_call: ToolCall,
        tool_def: ToolDef,
    ) -> PermissionDecision | None:
        if tool_def.shell_command_arg:
            command = str(tool_call.arguments.get(tool_def.shell_command_arg, "")).strip()
            for snippet in ("rm -rf", "mkfs", "shutdown", "reboot", "dd if="):
                if snippet in command:
                    return self._deny(
                        denied_calls,
                        tool_call.name,
                        f"Command blocked for safety: {snippet}",
                        "hard_guard.command",
                    )

        if tool_def.path_access == "write":
            path = str(tool_call.arguments.get("path", "")).strip()
            if path and not self._path_within_roots(path, policy.writable_roots):
                return self._deny(
                    denied_calls,
                    tool_call.name,
                    "Path is outside writable roots",
                    "hard_guard.writable_roots",
                )

        if tool_def.path_access == "read":
            path = str(tool_call.arguments.get("path", "")).strip()
            if path and not self._path_within_roots(path, policy.readable_roots):
                return self._deny(
                    denied_calls,
                    tool_call.name,
                    "Path is outside readable roots",
                    "hard_guard.readable_roots",
                )

        if tool_def.is_destructive:
            return PermissionDecision(
                action=PermissionAction.ASK,
                reason="Destructive action requires confirmation",
                rule_source="hard_guard.destructive",
                requires_user_input=True,
            )
        return None

    def _evaluate_rules(
        self,
        policy: AccessPolicy,
        approval_rules: list[ApprovalRule],
        tool_call: ToolCall,
    ) -> PermissionDecision | None:
        for rule in approval_rules:
            if rule.tool_name != tool_call.name:
                continue
            if rule.mode_scope is not None and rule.mode_scope != policy.mode:
                continue
            if rule.command_prefix is not None:
                command = str(tool_call.arguments.get("command", ""))
                if not command.startswith(rule.command_prefix):
                    continue
            if rule.path_prefix is not None:
                path = str(tool_call.arguments.get("path", ""))
                if not path.startswith(rule.path_prefix):
                    continue
            return PermissionDecision(
                action=rule.action,
                reason=f"Matched session rule for {tool_call.name}",
                rule_source="session_rule",
            )
        return None

    def _evaluate_mode(
        self,
        policy: AccessPolicy,
        tool_call: ToolCall,
        tool_def: ToolDef,
    ) -> PermissionDecision:
        mode = policy.mode

        if mode == PermissionMode.PLAN:
            if tool_def.is_read_only and not tool_def.is_networked:
                return self._allow("Allowed in plan mode: read-only local tool", "mode.plan")
            return self._deny([], tool_call.name, "Plan mode forbids side-effecting actions", "mode.plan")

        if mode == PermissionMode.DONT_ASK:
            if self._is_auto_allowed(tool_call, tool_def):
                return self._allow("Allowed by dont_ask low-risk rule", "mode.dont_ask")
            return self._deny([], tool_call.name, "dont_ask converts approval requests into deny", "mode.dont_ask")

        if mode == PermissionMode.ACCEPT_EDITS:
            if tool_def.path_access == "write" and self._path_within_roots(
                str(tool_call.arguments.get("path", "")),
                policy.writable_roots,
            ):
                return self._allow("Editing within writable roots is auto-approved", "mode.accept_edits")

        if mode == PermissionMode.AUTO and self._is_auto_allowed(tool_call, tool_def):
            return self._allow("Auto-approved low-risk action", "mode.auto")

        if tool_call.name in policy.confirm_tools or tool_def.requires_confirmation:
            return PermissionDecision(
                action=PermissionAction.ASK,
                reason="Action requires user confirmation",
                rule_source="tool.requires_confirmation",
                requires_user_input=True,
                can_auto_approve=mode == PermissionMode.AUTO,
            )

        if tool_def.is_read_only and not tool_def.is_networked:
            return self._allow("Read-only local tool allowed", "tool.read_only")

        if mode in {PermissionMode.AUTO, PermissionMode.ACCEPT_EDITS} and self._is_auto_allowed(tool_call, tool_def):
            return self._allow("Allowed by mode heuristic", f"mode.{mode.value}")

        return PermissionDecision(
            action=PermissionAction.ASK,
            reason="Action is not auto-approved in this mode",
            rule_source=f"mode.{mode.value}",
            requires_user_input=True,
            can_auto_approve=mode == PermissionMode.AUTO,
        )

    def _is_auto_allowed(self, tool_call: ToolCall, tool_def: ToolDef) -> bool:
        # AUTO mode with the default policy trusts the session sandbox and
        # single-user ownership: auto-approve every tool that isn't explicitly
        # marked destructive. Writes, edits, shell commands, network reads —
        # all fine for an autonomous agent running in Docker. The only gate
        # left is `is_destructive=True`, which no current built-in tool sets
        # (reserved for future things like `delete_repo`).
        if tool_def.is_destructive:
            return False
        return True

    def _path_within_roots(self, path: str, roots: tuple[str, ...]) -> bool:
        if not path:
            return True
        candidate = Path(path).resolve()
        for root in roots:
            root_path = Path(root).resolve()
            if candidate == root_path or root_path in candidate.parents:
                return True
        return False

    def _allow(self, reason: str, source: str) -> PermissionDecision:
        return PermissionDecision(action=PermissionAction.ALLOW, reason=reason, rule_source=source)

    def _deny(
        self,
        denied_calls: list[dict[str, str]],
        tool_name: str,
        reason: str,
        source: str,
    ) -> PermissionDecision:
        if denied_calls is not None:
            denied_calls.append({"tool": tool_name, "reason": reason})
        return PermissionDecision(action=PermissionAction.DENY, reason=reason, rule_source=source)
