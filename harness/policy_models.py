"""Shared access policy models and presets."""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.core.models import PermissionMode


@dataclass
class AccessPolicy:
    """Defines global trust mode plus optional hard allow/deny rules."""

    mode: PermissionMode = PermissionMode.DEFAULT
    allowed_tools: set[str] | None = None
    blocked_tools: set[str] = field(default_factory=set)
    tool_call_limits: dict[str, int] = field(default_factory=dict)
    confirm_tools: set[str] = field(default_factory=set)
    writable_roots: tuple[str, ...] = (".",)
    readable_roots: tuple[str, ...] = (".",)


POLICY_PLAN = AccessPolicy(mode=PermissionMode.PLAN)
POLICY_DEFAULT = AccessPolicy(mode=PermissionMode.DEFAULT)
POLICY_ACCEPT_EDITS = AccessPolicy(mode=PermissionMode.ACCEPT_EDITS)
POLICY_AUTO = AccessPolicy(mode=PermissionMode.AUTO)
POLICY_DONT_ASK = AccessPolicy(mode=PermissionMode.DONT_ASK)
POLICY_READONLY = AccessPolicy(
    mode=PermissionMode.DEFAULT,
    blocked_tools={"write_file", "edit_file", "run_command", "rag_index"},
)
POLICY_NO_SHELL = AccessPolicy(
    mode=PermissionMode.DEFAULT,
    blocked_tools={"run_command"},
)

PRESET_POLICIES: dict[str, AccessPolicy] = {
    "plan": POLICY_PLAN,
    "default": POLICY_DEFAULT,
    "accept_edits": POLICY_ACCEPT_EDITS,
    "auto": POLICY_AUTO,
    "dont_ask": POLICY_DONT_ASK,
    "readonly": POLICY_READONLY,
    "no_shell": POLICY_NO_SHELL,
    "unrestricted": POLICY_DEFAULT,
}


def get_policy(name: str) -> AccessPolicy:
    policy = PRESET_POLICIES.get(name)
    if policy is None:
        available = ", ".join(PRESET_POLICIES.keys())
        raise ValueError(f"Unknown policy: {name}. Available: {available}")
    return AccessPolicy(
        mode=policy.mode,
        allowed_tools=set(policy.allowed_tools) if policy.allowed_tools is not None else None,
        blocked_tools=set(policy.blocked_tools),
        tool_call_limits=dict(policy.tool_call_limits),
        confirm_tools=set(policy.confirm_tools),
        writable_roots=tuple(policy.writable_roots),
        readable_roots=tuple(policy.readable_roots),
    )
