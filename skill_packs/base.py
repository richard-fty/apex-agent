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

from agent.core.models import ToolDef


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

        Matching strategy:
        - Tokenize input into words + keep hyphenated forms
        - Short keywords (tickers): exact word match
        - Hyphenated keywords (btc-usd): substring match
        - Longer keywords: check if keyword appears in any word or vice versa
        - Keep auto-loading conservative: usually require 3+ meaningful matches

        Override for embedding-based matching in the future.
        """
        if not self.keywords:
            return 0.0

        input_lower = user_input.lower()
        # Tokenize: split on spaces, commas, periods — keep hyphens intact
        input_words = set(input_lower.replace(",", " ").replace(".", " ").replace(":", " ").split())
        # Also add the raw input for substring matching of hyphenated terms
        matches = 0
        for kw in self.keywords:
            kw_lower = kw.lower()
            if "-" in kw_lower:
                # Hyphenated (btc-usd, eth-usd): substring in raw input
                if kw_lower in input_lower:
                    matches += 1
            elif len(kw_lower) <= 4:
                # Short keywords (tickers like aapl, btc, rsi, ema):
                # must be a standalone word to avoid false positives
                if kw_lower in input_words:
                    matches += 1
            else:
                # Longer keywords (stock, trading, strategy, backtest, analyze):
                # check if keyword is contained in any input word or vice versa
                for w in input_words:
                    if len(w) < 3:
                        continue
                    if kw_lower in w or w in kw_lower:
                        matches += 1
                        break

        # Keep confidence low unless we see several domain-specific signals.
        if matches <= 1:
            return matches * 0.1
        if matches == 2:
            return 0.35
        if matches == 3:
            return 0.55
        if matches == 4:
            return 0.7
        return min(1.0, 0.75 + (matches - 5) * 0.05)
