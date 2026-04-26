"""System prompt construction with three-level progressive disclosure.

Level 1: Skill INDEX (always in prompt) — analyzed name + description + tool count
Level 2: Structured prompt (loaded via load_skill) — parsed workflow, rules, tools
Level 3: REFERENCE.md sections (read via read_skill_reference) — domain knowledge
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.skills.loader import SkillLoader

BASE_SYSTEM_PROMPT = """\
You are Apex Agent, a personal terminal agent for research, files, shell, and the web.

## Built-in Tools (always available)
- `read_file(path)` — Read file contents
- `write_file(path, content)` — Create or overwrite a file
- `edit_file(path, old_string, new_string)` — Replace a specific string in a file
- `list_dir(path)` — List directory contents
- `run_command(command)` — Execute a shell command
- `web_research(query, num_results?, fetch_top?, max_chars?)` — Search the web and gather sources in one call; leave `fetch_top` at `0` unless you explicitly need full page text

Some tools are surfaced dynamically by the runtime.
- Core tools are usually visible.
- Skill tools become visible when their skill is loaded.
- Retrieval or admin tools may only be surfaced when relevant or when explicitly approved.

## Internal Capabilities
Some capabilities are internal runtime mechanisms. Do not proactively explain or advertise internal skills,
skill packs, workflow names, or routing behavior to the user unless the user explicitly asks about them.
When speaking to the user, describe what you can help with in natural product terms, not internal architecture terms.

## Internal Capability Management
You have internal loadable capability packs for domain-specific tasks. Use these meta-tools only when needed:

- `list_skills()` — Inspect internal capability packs when you need domain-specific help
- `load_skill(name)` — Activate an internal capability pack
- `unload_skill(name)` — Deactivate an internal capability pack
- `read_skill_reference(name, section?)` — Read internal reference docs when needed

**Important:** Load a capability pack BEFORE trying to use its tools.
These are internal runtime mechanisms. Do not mention them to the user unless the user explicitly asks.

## How to Work
1. Read the user's request
2. If domain-specific help is needed, inspect internal capability packs and load one only when useful
3. Use tools step by step to accomplish the task
4. Read files before modifying them
5. If a tool fails, explain and try an alternative
6. Be efficient — don't make unnecessary tool calls
7. Respect approval boundaries — if a tool call is denied or requires confirmation, adapt your plan
8. Do not mention loaded skills, capability packs, or internal tool-loading behavior in your answer unless the user explicitly asks
"""


def build_language_instruction(response_language: str) -> str:
    """Build a stable response-language instruction for the system prompt.

    Placed at the very top of the system prompt (before everything else) and
    written in strong, unambiguous terms because providers like DeepSeek have
    a Chinese-language bias that a mild hint at the end of the prompt can't
    overcome.
    """
    language = (response_language or "").strip()
    if not language:
        return ""

    return (
        f"# Response Language: {language}\n"
        f"You MUST reply in {language} by default. Every user-facing message — "
        f"chat text, explanations, report bodies, narration between tool calls, "
        f"assistant notes, thinking steps — MUST be in {language}, even when the "
        f"user's prompt is in another language.\n"
        f"Technical identifiers are exempt: tool names, code, file paths, shell "
        f"commands, JSON fields, and URLs stay as-is.\n"
        f"Only reply in another language when the user explicitly asks for one "
        f"(e.g., 'reply in Chinese'), and only for that single response.\n\n"
    )


def build_skill_index(skill_loader: SkillLoader) -> str:
    """Build the Level 1 skill index from analyzed data.

    Uses the analyzer's compact index_entry for each skill.
    """
    available = skill_loader.available
    if not available:
        return ""

    lines = ["\n## Internal Capability Packs"]
    lines.append("This section is for internal routing only. Do not describe it to the user unless asked.")
    lines.append("| Capability | Description | Status |")
    lines.append("|---|---|---|")

    for name in sorted(available.keys()):
        index_entry = skill_loader.get_index_entry(name) or available[name].description
        status = "**loaded**" if name in skill_loader.loaded else "available"
        lines.append(f"| `{name}` | {index_entry} | {status} |")

    lines.append("")
    lines.append("*Use `load_skill(name)` only when domain-specific capability is needed.*")

    return "\n".join(lines) + "\n"


def build_system_prompt(
    skill_loader: SkillLoader,
    response_language: str = "English",
) -> str:
    """Build the full system prompt: base + skill index + loaded skill content."""
    # Language instruction goes FIRST — models that have a default-language
    # bias (e.g. DeepSeek → Chinese) ignore a gentle hint buried at the end.
    parts = [build_language_instruction(response_language), BASE_SYSTEM_PROMPT]

    # Keep skill discovery internal; only surface the index once a skill is loaded.
    if skill_loader.loaded:
        parts.append(build_skill_index(skill_loader))

    # Level 2: Include structured prompts for loaded skills
    for name in skill_loader.loaded:
        structured = skill_loader.get_structured_prompt(name)
        if structured:
            parts.append(f"\n---\n{structured}")

    return "\n".join(parts)
