"""Built-in filesystem tools: read, write, edit, list directory."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agent.artifacts import ArtifactKind, ArtifactSpec
from agent.core.models import ToolParameter
from agent.runtime.sandbox import get_default_sandbox
from agent.runtime.tool_context import (
    emit_artifact_append,
    emit_artifact_created,
    emit_artifact_finalized,
    emit_artifact_replace,
)
from tools.base import BuiltinTool


# Map common file extensions to (ArtifactKind, language hint for code).
# Anything not in the map becomes a generic FILE artifact.
_EXT_TO_ARTIFACT: dict[str, tuple[ArtifactKind, str | None]] = {
    ".md": (ArtifactKind.MARKDOWN, None),
    ".markdown": (ArtifactKind.MARKDOWN, None),
    ".json": (ArtifactKind.JSON, None),
    ".txt": (ArtifactKind.TEXT, None),
    ".py": (ArtifactKind.CODE, "python"),
    ".js": (ArtifactKind.CODE, "javascript"),
    ".ts": (ArtifactKind.CODE, "typescript"),
    ".tsx": (ArtifactKind.CODE, "tsx"),
    ".jsx": (ArtifactKind.CODE, "jsx"),
    ".html": (ArtifactKind.CODE, "html"),
    ".css": (ArtifactKind.CODE, "css"),
    ".sh": (ArtifactKind.CODE, "shell"),
    ".bash": (ArtifactKind.CODE, "shell"),
    ".yaml": (ArtifactKind.CODE, "yaml"),
    ".yml": (ArtifactKind.CODE, "yaml"),
    ".toml": (ArtifactKind.CODE, "toml"),
    ".go": (ArtifactKind.CODE, "go"),
    ".rs": (ArtifactKind.CODE, "rust"),
    ".java": (ArtifactKind.CODE, "java"),
    ".c": (ArtifactKind.CODE, "c"),
    ".h": (ArtifactKind.CODE, "c"),
    ".cpp": (ArtifactKind.CODE, "cpp"),
    ".sql": (ArtifactKind.CODE, "sql"),
}


def _artifact_for_path(path: str) -> tuple[ArtifactKind, str | None]:
    ext = Path(path).suffix.lower()
    return _EXT_TO_ARTIFACT.get(ext, (ArtifactKind.FILE, None))


class ReadFileTool(BuiltinTool):
    name = "read_file"
    description = "Read the contents of a file. Returns the file content as text."
    is_read_only = True
    is_concurrency_safe = True
    requires_confirmation = False
    mutates_state = False
    path_access = "read"
    parameters = [
        ToolParameter(name="path", type="string", description="Path to the file to read"),
        ToolParameter(
            name="limit",
            type="integer",
            description="Max number of lines to read (default: all)",
            required=False,
        ),
        ToolParameter(
            name="offset",
            type="integer",
            description="Line number to start reading from (0-based, default: 0)",
            required=False,
        ),
    ]

    async def execute(self, **kwargs: Any) -> str:
        path = kwargs["path"]
        limit = kwargs.get("limit")
        offset = kwargs.get("offset", 0)

        p = Path(path).resolve()
        if not p.exists():
            return f"Error: File not found: {path}"
        if not p.is_file():
            return f"Error: Not a file: {path}"

        text = get_default_sandbox().read_file(str(p), encoding="utf-8")
        lines = text.splitlines()

        if offset:
            lines = lines[offset:]
        if limit:
            lines = lines[:limit]

        numbered = [f"{i + offset + 1:4d} | {line}" for i, line in enumerate(lines)]
        return "\n".join(numbered)


class WriteFileTool(BuiltinTool):
    name = "write_file"
    description = "Write content to a file. Creates the file if it doesn't exist, overwrites if it does."
    requires_confirmation = True
    path_access = "write"
    parameters = [
        ToolParameter(name="path", type="string", description="Path to the file to write"),
        ToolParameter(name="content", type="string", description="Content to write to the file"),
    ]

    async def execute(self, **kwargs: Any) -> str:
        path = kwargs["path"]
        content = kwargs["content"]

        p = Path(path).resolve()
        get_default_sandbox().write_file(str(p), content, encoding="utf-8")

        # Emit artifact event stream so UIs can render the new file live.
        kind, language = _artifact_for_path(path)
        artifact_id = await emit_artifact_created(
            spec=ArtifactSpec(
                kind=kind,
                name=Path(path).name,
                language=language,
                description=f"Written to {path}",
            )
        )
        if artifact_id:
            await emit_artifact_replace(artifact_id, content)
            await emit_artifact_finalized(artifact_id)

        return f"Written {len(content)} chars to {path}"


class EditFileTool(BuiltinTool):
    name = "edit_file"
    description = "Replace a specific string in a file with new content. The old_string must match exactly."
    requires_confirmation = True
    path_access = "write"
    parameters = [
        ToolParameter(name="path", type="string", description="Path to the file to edit"),
        ToolParameter(name="old_string", type="string", description="Exact string to find and replace"),
        ToolParameter(name="new_string", type="string", description="String to replace it with"),
    ]

    async def execute(self, **kwargs: Any) -> str:
        path = kwargs["path"]
        old_string = kwargs["old_string"]
        new_string = kwargs["new_string"]

        p = Path(path).resolve()
        if not p.exists():
            return f"Error: File not found: {path}"

        text = get_default_sandbox().read_file(str(p), encoding="utf-8")
        count = text.count(old_string)
        if count == 0:
            return f"Error: old_string not found in {path}"
        if count > 1:
            return f"Error: old_string found {count} times — must be unique. Provide more context."

        new_text = text.replace(old_string, new_string, 1)
        get_default_sandbox().write_file(str(p), new_text, encoding="utf-8")

        # Emit a fresh artifact reflecting the edited file for the UI.
        kind, language = _artifact_for_path(path)
        artifact_id = await emit_artifact_created(
            spec=ArtifactSpec(
                kind=kind,
                name=Path(path).name,
                language=language,
                description=f"Edited {path}",
            )
        )
        if artifact_id:
            await emit_artifact_replace(artifact_id, new_text)
            await emit_artifact_finalized(artifact_id)

        return f"Replaced 1 occurrence in {path}"


class ListDirTool(BuiltinTool):
    name = "list_dir"
    description = "List files and directories in a given path. Returns names with type indicators."
    is_read_only = True
    is_concurrency_safe = True
    requires_confirmation = False
    mutates_state = False
    path_access = "read"
    parameters = [
        ToolParameter(
            name="path",
            type="string",
            description="Directory path to list (default: current directory)",
            required=False,
            default=".",
        ),
    ]

    async def execute(self, **kwargs: Any) -> str:
        path = kwargs.get("path", ".")
        p = Path(path).resolve()

        if not p.exists():
            return f"Error: Directory not found: {path}"
        if not p.is_dir():
            return f"Error: Not a directory: {path}"

        entries = get_default_sandbox().list_dir(str(p))
        lines = []
        for entry in entries:
            if entry.name.startswith("."):
                continue  # Skip hidden files by default
            indicator = "/" if entry.is_dir() else ""
            size = ""
            if entry.is_file():
                size = f"  ({_human_size(entry.stat().st_size)})"
            lines.append(f"  {entry.name}{indicator}{size}")

        if not lines:
            return f"{path}: (empty directory)"
        return f"{path}:\n" + "\n".join(lines)


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"
