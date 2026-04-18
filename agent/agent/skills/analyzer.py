"""Skill Analyzer — parses SKILL.md and REFERENCE.md into structured data.

Extracts:
  - Trigger conditions (when to use this skill)
  - Workflow steps (ordered)
  - Rules/constraints
  - Declared tools (mentioned in SKILL.md)
  - Reference sections (available in REFERENCE.md)
  - Validates declared tools vs actually registered tools
  - Builds compact index entry and structured prompt
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from skill_packs.base import SkillPack


@dataclass
class WorkflowStep:
    """A single step in a skill's workflow."""
    order: int
    action: str          # e.g. "Fetch market data for the requested symbol(s)"
    tool_hint: str = ""  # e.g. "fetch_market_data" — extracted if mentioned


@dataclass
class ReferenceSection:
    """A section in REFERENCE.md."""
    heading: str
    level: int           # Markdown heading level (1-6)
    char_count: int      # Size of section content
    subsections: list[str] = field(default_factory=list)


@dataclass
class AnalyzedSkill:
    """Fully parsed, structured representation of a skill pack."""

    # Identity
    name: str
    description: str

    # Parsed from SKILL.md
    when_to_use: list[str]                          # Trigger conditions
    workflow: list[WorkflowStep]                    # Ordered steps
    rules: list[str]                                # Constraints
    declared_tools: list[DeclaredTool]              # Tools mentioned in SKILL.md
    common_patterns: list[str]                      # Usage patterns/examples
    raw_skill_md: str                               # Original SKILL.md content

    # Parsed from REFERENCE.md
    reference_sections: list[ReferenceSection]       # Section index
    raw_reference_md: str                            # Original REFERENCE.md content

    # Validation
    registered_tool_names: list[str]                # Tools actually registered in skill.py
    missing_tools: list[str]                        # Declared in SKILL.md but not registered
    extra_tools: list[str]                          # Registered but not declared in SKILL.md

    # Pre-built outputs
    index_entry: str                                # Compact one-liner for Level 1
    structured_prompt: str                          # Clean Level 2 content for loading


@dataclass
class DeclaredTool:
    """A tool declared in SKILL.md."""
    name: str
    description: str
    is_available: bool = True   # False if not yet registered (e.g. "Phase 2")


class SkillAnalyzer:
    """Parses skill pack files into structured AnalyzedSkill objects."""

    def analyze(self, skill: SkillPack) -> AnalyzedSkill:
        """Analyze a skill pack — parse its SKILL.md and REFERENCE.md."""

        skill_md = skill.skill_md
        reference_md = skill.reference_md

        # Get registered tool names
        registered_tools = [td.name for td, _ in skill.get_tools()]

        # Parse SKILL.md sections
        when_to_use = self._parse_list_section(skill_md, "When to Use")
        workflow = self._parse_workflow(skill_md)
        rules = self._parse_list_section(skill_md, "Rules")
        declared_tools = self._parse_tools_section(skill_md, registered_tools)
        common_patterns = self._parse_list_section(skill_md, "Common Patterns")

        # Parse REFERENCE.md structure
        reference_sections = self._parse_reference_structure(reference_md)

        # Validation: cross-reference declared vs registered
        declared_names = {t.name for t in declared_tools}
        registered_set = set(registered_tools)
        missing = sorted(declared_names - registered_set)
        extra = sorted(registered_set - declared_names)

        # Mark unavailable tools
        for dt in declared_tools:
            dt.is_available = dt.name in registered_set

        # Build index entry (Level 1)
        tool_count = len(registered_tools)
        ref_count = len(reference_sections)
        index_entry = (
            f"{skill.description} "
            f"[{tool_count} tools, {ref_count} ref sections]"
        )

        # Build structured prompt (Level 2)
        structured_prompt = self._build_structured_prompt(
            skill, workflow, rules, declared_tools, reference_sections
        )

        return AnalyzedSkill(
            name=skill.name,
            description=skill.description,
            when_to_use=when_to_use,
            workflow=workflow,
            rules=rules,
            declared_tools=declared_tools,
            common_patterns=common_patterns,
            raw_skill_md=skill_md,
            reference_sections=reference_sections,
            raw_reference_md=reference_md,
            registered_tool_names=registered_tools,
            missing_tools=missing,
            extra_tools=extra,
            index_entry=index_entry,
            structured_prompt=structured_prompt,
        )

    # ── SKILL.md Parsers ──────────────────────────────────────────────

    def _parse_list_section(self, markdown: str, heading: str) -> list[str]:
        """Extract bullet-point items from a section."""
        section = _extract_section(markdown, heading)
        if not section:
            return []

        items = []
        for line in section.split("\n"):
            stripped = line.strip()
            # Match markdown list items: -, *, or numbered
            match = re.match(r"^[-*]\s+(.+)$", stripped)
            if not match:
                match = re.match(r"^\d+\.\s+(.+)$", stripped)
            if match:
                items.append(match.group(1).strip())
        return items

    def _parse_workflow(self, markdown: str) -> list[WorkflowStep]:
        """Extract ordered workflow steps."""
        section = _extract_section(markdown, "Workflow")
        if not section:
            return []

        steps = []
        for line in section.split("\n"):
            stripped = line.strip()
            # Match numbered steps: 1. **Fetch data** — description
            match = re.match(r"^\d+\.\s+(?:\*\*(.+?)\*\*\s*[-—]\s*)?(.+)$", stripped)
            if match:
                action_name = match.group(1) or ""
                action_desc = match.group(2).strip()
                action = f"{action_name}: {action_desc}" if action_name else action_desc

                # Try to extract tool hint from backticks
                tool_match = re.search(r"`(\w+)`", action_desc)
                tool_hint = tool_match.group(1) if tool_match else ""

                steps.append(WorkflowStep(
                    order=len(steps) + 1,
                    action=action,
                    tool_hint=tool_hint,
                ))
        return steps

    def _parse_tools_section(
        self, markdown: str, registered_tools: list[str]
    ) -> list[DeclaredTool]:
        """Extract tool declarations from SKILL.md."""
        section = _extract_section(markdown, "Available Tools")
        if not section:
            # Fall back: scan entire doc for backtick tool patterns
            return self._scan_for_tools(markdown, registered_tools)

        tools = []
        for line in section.split("\n"):
            stripped = line.strip()
            # Match: - `tool_name(params)` — description
            match = re.match(r"^[-*]\s+`(\w+)\(.*?\)`\s*[-—]\s*(.+)$", stripped)
            if match:
                name = match.group(1)
                desc = match.group(2).strip()
                tools.append(DeclaredTool(
                    name=name,
                    description=desc,
                    is_available=name in registered_tools,
                ))
        return tools

    def _scan_for_tools(
        self, markdown: str, registered_tools: list[str]
    ) -> list[DeclaredTool]:
        """Fallback: scan markdown for tool-like patterns."""
        tools = []
        seen = set()
        # Match `tool_name(...)` patterns
        for match in re.finditer(r"`(\w+)\([^)]*\)`", markdown):
            name = match.group(1)
            if name not in seen and name in registered_tools:
                seen.add(name)
                tools.append(DeclaredTool(
                    name=name,
                    description="(extracted from skill docs)",
                    is_available=True,
                ))
        return tools

    # ── REFERENCE.md Parsers ──────────────────────────────────────────

    def _parse_reference_structure(self, markdown: str) -> list[ReferenceSection]:
        """Parse REFERENCE.md into a section index with sizes."""
        if not markdown:
            return []

        sections: list[ReferenceSection] = []
        lines = markdown.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            if stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                heading = stripped.lstrip("#").strip()

                # Collect content until next heading of same/higher level
                content_lines = []
                subsections = []
                j = i + 1
                while j < len(lines):
                    next_line = lines[j].strip()
                    if next_line.startswith("#"):
                        next_level = len(next_line) - len(next_line.lstrip("#"))
                        if next_level <= level:
                            break
                        # Sub-heading
                        subsections.append(next_line.lstrip("#").strip())
                    content_lines.append(lines[j])
                    j += 1

                content = "\n".join(content_lines)
                sections.append(ReferenceSection(
                    heading=heading,
                    level=level,
                    char_count=len(content),
                    subsections=subsections,
                ))
                i = j
            else:
                i += 1

        return sections

    # ── Output Builders ───────────────────────────────────────────────

    def _build_structured_prompt(
        self,
        skill: SkillPack,
        workflow: list[WorkflowStep],
        rules: list[str],
        declared_tools: list[DeclaredTool],
        reference_sections: list[ReferenceSection],
    ) -> str:
        """Build a clean, structured prompt for Level 2 loading."""
        parts = [f"# Skill: {skill.name}", f"{skill.description}", ""]

        # Workflow
        if workflow:
            parts.append("## Workflow")
            for step in workflow:
                tool_hint = f" → `{step.tool_hint}`" if step.tool_hint else ""
                parts.append(f"  {step.order}. {step.action}{tool_hint}")
            parts.append("")

        # Rules
        if rules:
            parts.append("## Rules")
            for rule in rules:
                parts.append(f"  - {rule}")
            parts.append("")

        # Available tools
        available_tools = [t for t in declared_tools if t.is_available]
        unavailable_tools = [t for t in declared_tools if not t.is_available]

        if available_tools:
            parts.append("## Tools Ready")
            for tool in available_tools:
                parts.append(f"  - `{tool.name}` — {tool.description}")
            parts.append("")

        if unavailable_tools:
            parts.append("## Tools Not Yet Available")
            for tool in unavailable_tools:
                parts.append(f"  - `{tool.name}` — {tool.description} (coming soon)")
            parts.append("")

        # Reference index
        if reference_sections:
            top_sections = [s for s in reference_sections if s.level <= 2]
            if top_sections:
                parts.append("## Reference Docs Available")
                parts.append("Use `read_skill_reference(name)` to access:")
                for sec in top_sections:
                    size = f"~{sec.char_count // 2} tokens"
                    subs = f" ({', '.join(sec.subsections)})" if sec.subsections else ""
                    parts.append(f"  - {sec.heading}{subs} [{size}]")
                parts.append("")

        return "\n".join(parts)


# ── Utility ───────────────────────────────────────────────────────────

def _extract_section(markdown: str, heading: str) -> str | None:
    """Extract content under a specific heading (case-insensitive)."""
    lines = markdown.split("\n")
    heading_lower = heading.lower().strip()

    capturing = False
    captured: list[str] = []
    capture_level = 0

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped.lstrip("#").strip().lower()

            if not capturing and heading_lower in title:
                capturing = True
                capture_level = level
                continue  # Don't include the heading itself

            if capturing and level <= capture_level:
                break

        if capturing:
            captured.append(line)

    if captured:
        return "\n".join(captured).strip()
    return None
