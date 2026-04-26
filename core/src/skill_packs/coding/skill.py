"""Coding skill metadata."""

from __future__ import annotations

from typing import Any

from agent.core.models import ToolDef
from skill_packs.base import SkillPack, ToolHandler
from skill_packs.coding.tools import get_tools


class CodingSkill(SkillPack):
    @property
    def name(self) -> str:
        return "coding"

    @property
    def description(self) -> str:
        return "Build, edit, and validate lightweight frontend apps."

    @property
    def keywords(self) -> list[str]:
        return [
            "code",
            "coding",
            "build",
            "vite",
            "react",
            "typescript",
            "frontend",
            "app",
            "fix",
            "implement",
            "component",
            "playwright",
        ]

    def get_tools(self) -> list[tuple[ToolDef, ToolHandler]]:
        return get_tools()

