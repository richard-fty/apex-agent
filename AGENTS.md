# AGENTS.md

This repository is primarily worked on in Chinese.

## Language

- Default to replying in Chinese unless the user explicitly requests another language.
- Keep code, file paths, shell commands, API names, JSON fields, environment variable names, and other technical identifiers unchanged.
- When mixing Chinese with code or commands, prefer concise explanations.

## Working Style

- Read the relevant files before editing.
- Make focused, minimal changes that fit the existing structure.
- Prefer concrete implementation over long planning when the task is clear.
- When proposing refactors, anchor them to the current codebase and file structure.

## Apex Agent Preferences

- Treat tools as capability boundaries.
- Prefer conservative behavior for state-changing or networked actions.
- Distinguish clearly between core tools, skill tools, and retrieval or memory-related tools.
- Favor context management and retrieval quality over adding more prompt instructions.

## Output

- Be concise by default.
- Summaries should emphasize architecture, risks, and next practical steps.
