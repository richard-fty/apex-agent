"""Base class for skill packs.

A skill pack is a folder containing:
  - SKILL.md      — What the skill does, workflow, rules (loaded as prompt)
  - REFERENCE.md  — Domain knowledge the agent can read on demand
  - scripts/      — Runnable scripts for heavy computation
  - tools.py      — Tool implementations
  - skill.py      — Metadata + registration (this base class)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Awaitable

from agent.models import ToolDef


ToolHandler = Callable[..., Awaitable[str] | str]


class SkillPack(ABC):
    """A loadable skill pack with docs, tools, and scripts."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        ...

    @property
    @abstractmethod
    def keywords(self) -> list[str]:
        ...

    @property
    def skill_dir(self) -> Path:
        """Path to the skill pack directory."""
        return Path(__file__).parent / self.name.replace(".", "/")

    @property
    def skill_md(self) -> str:
        """Read SKILL.md — loaded as prompt addition when skill is active."""
        path = self.skill_dir / "SKILL.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    @property
    def reference_md(self) -> str:
        """Read REFERENCE.md — domain knowledge available on demand."""
        path = self.skill_dir / "REFERENCE.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    @property
    def prompt_addition(self) -> str:
        """System prompt addition = SKILL.md content."""
        return self.skill_md

    @abstractmethod
    def get_tools(self) -> list[tuple[ToolDef, ToolHandler]]:
        """Return (tool_definition, handler) pairs."""
        ...

    def matches_intent(self, user_input: str) -> float:
        """Score 0.0-1.0 how well this skill matches user input.
        Default: keyword matching. Override for embedding-based.
        """
        input_lower = user_input.lower()
        matches = sum(1 for kw in self.keywords if kw in input_lower)
        if not self.keywords:
            return 0.0
        return min(1.0, matches / max(1, len(self.keywords) * 0.3))
