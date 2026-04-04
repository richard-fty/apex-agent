"""Skill loader — three-level progressive disclosure with analyzer.

Level 1: INDEX — analyzed skill name + description + tool count, always in system prompt
Level 2: SKILL.md — analyzed into structured prompt, loaded via load_skill()
Level 3: REFERENCE.md — section index known, read on demand via read_skill_reference()

On discover():
  1. Find all skill packs
  2. Run SkillAnalyzer on each → produces AnalyzedSkill
  3. Validates declared tools vs registered tools (logs warnings)
  4. Builds index entries for the system prompt

On load_skill():
  1. Register skill's tools into the dispatcher
  2. Return the structured_prompt (not raw SKILL.md)

On read_skill_reference():
  1. Return specific section from REFERENCE.md (or full doc)
"""

from __future__ import annotations

import logging
from typing import Any

from agent.skill_analyzer import AnalyzedSkill, SkillAnalyzer
from agent.tool_dispatch import ToolDispatch
from skills.base import SkillPack
from skills.registry import discover_skills

logger = logging.getLogger(__name__)


class SkillLoader:
    """Manages progressive disclosure of skill packs with analysis."""

    def __init__(self, tool_dispatch: ToolDispatch) -> None:
        self.tool_dispatch = tool_dispatch
        self.available: dict[str, SkillPack] = {}
        self.loaded: dict[str, SkillPack] = {}
        self.analyzed: dict[str, AnalyzedSkill] = {}
        self._analyzer = SkillAnalyzer()

    def discover(self) -> None:
        """Scan for all available skill packs and analyze them."""
        self.available = discover_skills()

        for name, skill in self.available.items():
            analyzed = self._analyzer.analyze(skill)
            self.analyzed[name] = analyzed

            # Log validation results (debug level — not shown to user)
            if analyzed.missing_tools:
                logger.debug(
                    "Skill '%s' declares tools not yet registered: %s",
                    name, ", ".join(analyzed.missing_tools),
                )
            if analyzed.extra_tools:
                logger.debug(
                    "Skill '%s' has registered tools not declared in SKILL.md: %s",
                    name, ", ".join(analyzed.extra_tools),
                )

            logger.debug(
                "Skill '%s' analyzed: %d workflow steps, %d rules, "
                "%d tools (%d available), %d reference sections",
                name,
                len(analyzed.workflow),
                len(analyzed.rules),
                len(analyzed.declared_tools),
                len(analyzed.registered_tool_names),
                len(analyzed.reference_sections),
            )

    def load_skill(self, name: str) -> bool:
        """Load a skill pack — register its tools.

        Returns True if loaded, False if not found or already loaded.
        """
        if name in self.loaded:
            return False

        skill = self.available.get(name)
        if skill is None:
            return False

        for tool_def, handler in skill.get_tools():
            self.tool_dispatch.register(tool_def, handler)

        self.loaded[name] = skill
        return True

    def unload_skill(self, name: str) -> bool:
        """Unload a skill pack — remove its tools.

        Returns True if unloaded, False if not loaded.
        """
        skill = self.loaded.pop(name, None)
        if skill is None:
            return False

        for tool_def, _ in skill.get_tools():
            self.tool_dispatch.unregister(tool_def.name)

        return True

    def get_structured_prompt(self, name: str) -> str | None:
        """Get the analyzed structured prompt for a skill (Level 2)."""
        analyzed = self.analyzed.get(name)
        if analyzed:
            return analyzed.structured_prompt
        return None

    def get_index_entry(self, name: str) -> str | None:
        """Get the compact index entry for a skill (Level 1)."""
        analyzed = self.analyzed.get(name)
        if analyzed:
            return analyzed.index_entry
        return None

    def get_reference_sections(self, name: str) -> list[str]:
        """Get available reference section headings for a skill."""
        analyzed = self.analyzed.get(name)
        if analyzed:
            return [s.heading for s in analyzed.reference_sections]
        return []

    def pre_load_by_intent(self, user_input: str, threshold: float = 0.6) -> list[str]:
        """Pre-load skills that match the user's input before the first LLM call.

        This saves one tool-call round-trip — the agent gets the skill's tools
        and prompt immediately instead of having to call load_skill() first.

        Returns list of skill names that were pre-loaded.
        """
        pre_loaded = []
        for name, skill in self.available.items():
            if name in self.loaded:
                continue
            score = skill.matches_intent(user_input)
            if score >= threshold:
                if self.load_skill(name):
                    pre_loaded.append(name)
                    logger.debug("Pre-loaded skill '%s' (score: %.2f)", name, score)
        return pre_loaded

    def get_loaded_skill_names(self) -> list[str]:
        return list(self.loaded.keys())

    def get_available_skill_names(self) -> list[str]:
        return list(self.available.keys())
