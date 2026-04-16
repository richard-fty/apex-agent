"""Meta-tools for skill management — the agent uses these to control progressive disclosure.

- list_skills: Show analyzed index (Level 1)
- load_skill: Activate a skill, return structured prompt (Level 2)
- unload_skill: Deactivate a skill, free context
- read_skill_reference: Read parsed reference sections (Level 3)

These tools use the SkillAnalyzer's output for structured, validated responses.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from agent.core.models import ToolDef, ToolGroup, ToolParameter

if TYPE_CHECKING:
    from agent.skills.loader import SkillLoader


class SkillMetaTools:
    """Meta-tool handlers bound to a SkillLoader instance."""

    def __init__(self, skill_loader: SkillLoader) -> None:
        self._loader = skill_loader

    # -- Tool definitions ---------------------------------------------------

    @staticmethod
    def list_skills_def() -> ToolDef:
        return ToolDef(
            name="list_skills",
            description=(
                "List all available skill packs with descriptions, tool counts, "
                "and reference sections. Use this to decide which skills to load."
            ),
            parameters=[],
            is_read_only=True,
            is_concurrency_safe=True,
            requires_confirmation=False,
            mutates_state=False,
            tool_group=ToolGroup.RUNTIME,
        )

    @staticmethod
    def load_skill_def() -> ToolDef:
        return ToolDef(
            name="load_skill",
            description=(
                "Load a skill pack by name. Returns the skill's workflow, rules, "
                "available tools, and reference index. You must load a skill "
                "before using its domain-specific tools."
            ),
            parameters=[
                ToolParameter(
                    name="name",
                    type="string",
                    description="Name of the skill pack to load (from list_skills output)",
                ),
            ],
            requires_confirmation=False,
            mutates_state=False,
            tool_group=ToolGroup.RUNTIME,
        )

    @staticmethod
    def unload_skill_def() -> ToolDef:
        return ToolDef(
            name="unload_skill",
            description=(
                "Unload a skill pack to free context window space. "
                "Its tools will no longer be available."
            ),
            parameters=[
                ToolParameter(
                    name="name",
                    type="string",
                    description="Name of the skill pack to unload",
                ),
            ],
            requires_confirmation=False,
            mutates_state=False,
            tool_group=ToolGroup.RUNTIME,
        )

    @staticmethod
    def read_skill_reference_def() -> ToolDef:
        return ToolDef(
            name="read_skill_reference",
            description=(
                "Read a skill's reference documentation for domain knowledge. "
                "Optionally specify a section heading to read only that part."
            ),
            parameters=[
                ToolParameter(
                    name="name",
                    type="string",
                    description="Name of the skill pack",
                ),
                ToolParameter(
                    name="section",
                    type="string",
                    description="Optional: section heading to extract (omit for full doc)",
                    required=False,
                ),
            ],
            is_read_only=True,
            is_concurrency_safe=True,
            requires_confirmation=False,
            mutates_state=False,
            tool_group=ToolGroup.RUNTIME,
        )

    # -- Tool handlers ------------------------------------------------------

    async def list_skills(self) -> str:
        available = self._loader.available
        if not available:
            return "No skill packs installed."

        lines = ["# Available Skills", ""]

        for name in sorted(available.keys()):
            analyzed = self._loader.analyzed.get(name)
            status = "LOADED" if name in self._loader.loaded else "available"
            lines.append(f"## [{status}] {name}")

            if analyzed:
                lines.append(f"  {analyzed.description}")
                lines.append(f"  Tools: {len(analyzed.registered_tool_names)} available"
                             f" ({', '.join(analyzed.registered_tool_names)})")

                if analyzed.workflow:
                    lines.append(f"  Workflow: {len(analyzed.workflow)} steps")

                if analyzed.reference_sections:
                    top_sections = [s.heading for s in analyzed.reference_sections if s.level <= 2]
                    lines.append(f"  Reference: {', '.join(top_sections)}")

                if analyzed.missing_tools:
                    lines.append(f"  Note: {len(analyzed.missing_tools)} tools not yet implemented")
            else:
                lines.append(f"  {available[name].description}")

            lines.append("")

        loaded_names = self._loader.get_loaded_skill_names()
        if loaded_names:
            lines.append(f"Currently loaded: {', '.join(loaded_names)}")
        else:
            lines.append("No skills loaded. Use load_skill(name) to activate one.")

        return "\n".join(lines)

    async def load_skill(self, name: str) -> str:
        if name in self._loader.loaded:
            # Already loaded — return the structured prompt as a reminder
            structured = self._loader.get_structured_prompt(name)
            return f"Skill '{name}' is already loaded.\n\n{structured or ''}"

        if name not in self._loader.available:
            available_names = ", ".join(sorted(self._loader.available.keys()))
            return f"Unknown skill: '{name}'. Available: {available_names}"

        success = self._loader.load_skill(name)
        if not success:
            return f"Failed to load skill '{name}'."

        # Return the analyzed structured prompt (not raw SKILL.md)
        structured = self._loader.get_structured_prompt(name)
        analyzed = self._loader.analyzed.get(name)

        result_parts = [f"Skill '{name}' loaded successfully."]

        if analyzed:
            tool_names = analyzed.registered_tool_names
            result_parts.append(f"New tools available: {', '.join(tool_names)}")

        if structured:
            result_parts.append(f"\n{structured}")

        return "\n".join(result_parts)

    async def unload_skill(self, name: str) -> str:
        if name not in self._loader.loaded:
            return f"Skill '{name}' is not currently loaded."

        self._loader.unload_skill(name)
        return f"Skill '{name}' unloaded. Its tools are no longer available."

    async def read_skill_reference(self, name: str, section: str | None = None) -> str:
        skill = self._loader.available.get(name)
        if skill is None:
            return f"Unknown skill: '{name}'."

        reference = skill.reference_md
        if not reference:
            return f"Skill '{name}' has no reference documentation."

        analyzed = self._loader.analyzed.get(name)

        # If no section specified, show section index + ask to pick
        if not section:
            if analyzed and analyzed.reference_sections:
                lines = [f"# {name} Reference — Sections Available", ""]
                for sec in analyzed.reference_sections:
                    indent = "  " * (sec.level - 1)
                    size = f"~{sec.char_count // 2} tokens"
                    lines.append(f"{indent}- **{sec.heading}** [{size}]")
                    for sub in sec.subsections:
                        lines.append(f"{indent}  - {sub}")
                lines.append("")
                lines.append("Specify a section name to read it, e.g.:")
                lines.append(f'  read_skill_reference("{name}", "Technical Indicators")')
                return "\n".join(lines)
            else:
                # No sections parsed — return full doc
                return reference

        # Extract specific section
        extracted = _extract_section(reference, section)
        if extracted:
            return extracted

        # Section not found — suggest available ones
        if analyzed and analyzed.reference_sections:
            available_headings = [s.heading for s in analyzed.reference_sections]
            return (
                f"Section '{section}' not found in {name} reference.\n"
                f"Available sections: {', '.join(available_headings)}"
            )

        return f"Section '{section}' not found. Full reference:\n\n{reference}"

    # -- Registration helper ------------------------------------------------

    def get_tool_pairs(self) -> list[tuple[ToolDef, Any]]:
        """Return all meta-tool (definition, handler) pairs."""
        return [
            (self.list_skills_def(), self.list_skills),
            (self.load_skill_def(), self.load_skill),
            (self.unload_skill_def(), self.unload_skill),
            (self.read_skill_reference_def(), self.read_skill_reference),
        ]


def _extract_section(markdown: str, heading: str) -> str | None:
    """Extract a section from markdown by heading text (case-insensitive)."""
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
                captured.append(line)
                continue

            if capturing and level <= capture_level:
                break

        if capturing:
            captured.append(line)

    if captured:
        return "\n".join(captured).strip()
    return None
