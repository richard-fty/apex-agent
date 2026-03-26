"""System prompt construction with three-level progressive disclosure.

Level 1: Skill INDEX (always in prompt) — analyzed name + description + tool count
Level 2: Structured prompt (loaded via load_skill) — parsed workflow, rules, tools
Level 3: REFERENCE.md sections (read via read_skill_reference) — domain knowledge
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.skill_loader import SkillLoader

BASE_SYSTEM_PROMPT = """\
You are an autonomous general-purpose agent running inside a benchmark harness.

## Built-in Tools (always available)
- `read_file(path)` — Read file contents
- `write_file(path, content)` — Create or overwrite a file
- `edit_file(path, old_string, new_string)` — Replace a specific string in a file
- `list_dir(path)` — List directory contents
- `run_command(command)` — Execute a shell command
- `web_search(query)` — Search the web
- `web_fetch(url)` — Fetch a web page

## Skill Management
You have loadable skill packs for domain-specific tasks. Use these meta-tools:

- `list_skills()` — Show all available skills with descriptions
- `load_skill(name)` — Activate a skill (adds its tools and workflow to your context)
- `unload_skill(name)` — Deactivate a skill (frees context space)
- `read_skill_reference(name, section?)` — Read domain knowledge from a skill's reference docs

**Important:** Load a skill BEFORE trying to use its tools.

## How to Work
1. Read the user's request
2. Check the skill index below — load relevant skills if needed
3. Use tools step by step to accomplish the task
4. Read files before modifying them
5. If a tool fails, explain and try an alternative
6. Be efficient — don't make unnecessary tool calls
"""


def build_skill_index(skill_loader: SkillLoader) -> str:
    """Build the Level 1 skill index from analyzed data.

    Uses the analyzer's compact index_entry for each skill.
    """
    available = skill_loader.available
    if not available:
        return "\n## Available Skills\nNo skill packs installed.\n"

    lines = ["\n## Available Skills"]
    lines.append("| Skill | Description | Status |")
    lines.append("|---|---|---|")

    for name in sorted(available.keys()):
        index_entry = skill_loader.get_index_entry(name) or available[name].description
        status = "**loaded**" if name in skill_loader.loaded else "available"
        lines.append(f"| `{name}` | {index_entry} | {status} |")

    lines.append("")
    lines.append("*Use `load_skill(name)` to activate a skill and access its tools.*")

    return "\n".join(lines) + "\n"


def build_system_prompt(skill_loader: SkillLoader) -> str:
    """Build the full system prompt: base + skill index + loaded skill content."""
    parts = [BASE_SYSTEM_PROMPT]

    # Level 1: Always include skill index
    parts.append(build_skill_index(skill_loader))

    # Level 2: Include structured prompts for loaded skills
    for name in skill_loader.loaded:
        structured = skill_loader.get_structured_prompt(name)
        if structured:
            parts.append(f"\n---\n{structured}")

    return "\n".join(parts)
