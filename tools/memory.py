"""Memory tools — recall_session, remember, forget.

recall_session: query the session archive for specific old details (FTS5 BM25).
remember:       model proactively pins a fact in Zone 1.
forget:         model removes a stale/wrong fact from Zone 1.

These give the model active control over its own memory, complementing the
passive fact extraction that runs at eviction time.
"""

from __future__ import annotations

from typing import Any

from agent.core.models import ToolDef, ToolGroup, ToolParameter
from agent.session.archive import SessionArchive
from tools.base import BuiltinTool


class RecallSessionTool(BuiltinTool):
    name = "recall_session"
    description = (
        "Retrieve specific details from earlier in this session that may have "
        "been compressed out of the current context. Use when you know a fact "
        "or detail existed but can't see it in the current context. "
        "Uses keyword search — include concrete terms (names, numbers, tool names)."
    )
    parameters = [
        ToolParameter(
            name="query",
            type="string",
            description="Search query — use specific terms from the detail you need",
        ),
    ]
    is_read_only = True
    is_concurrency_safe = True
    requires_confirmation = False
    mutates_state = False
    tool_group = ToolGroup.ADMIN

    _archive: SessionArchive | None = None
    _session_id: str | None = None

    async def execute(self, **kwargs: Any) -> str:
        if self._archive is None or self._session_id is None:
            return "Error: session archive not available."

        query = kwargs.get("query", "").strip()
        if not query:
            return "Error: query cannot be empty."

        try:
            results = self._archive.recall(self._session_id, query, limit=3)
        except Exception as exc:
            return f"Error searching archive: {exc}"

        if not results:
            return (
                "No matching events found in this session's archive. "
                "Try different search terms — use specific names, numbers, or tool names."
            )

        parts = []
        for r in results:
            parts.append(f"[turn {r['seq']}, {r['event_type']}]\n{r['fragment']}")
        return "\n\n".join(parts)


class RememberTool(BuiltinTool):
    name = "remember"
    description = (
        "Pin a fact in your working memory (Zone 1) so it stays visible in "
        "every future turn. Use for key data points, decisions, or user "
        "preferences you'll need later. Each fact costs ~15 tokens of "
        "permanent context."
    )
    parameters = [
        ToolParameter(name="fact", type="string", description="The fact to remember"),
        ToolParameter(
            name="tags", type="string",
            description="Comma-separated tags for categorization (e.g. 'decision,architecture')",
            required=False,
        ),
    ]
    is_read_only = False
    requires_confirmation = False
    mutates_state = False
    tool_group = ToolGroup.ADMIN

    _memory_manager: Any = None  # will be set to ContextManager

    async def execute(self, **kwargs: Any) -> str:
        if self._memory_manager is None:
            return "Error: memory manager not available."

        fact = kwargs.get("fact", "").strip()
        if not fact:
            return "Error: fact cannot be empty."

        tags = [t.strip() for t in kwargs.get("tags", "").split(",") if t.strip()]
        self._memory_manager.pin_fact(fact, tags=tags)
        count = len(self._memory_manager.pinned_facts)
        cap = self._memory_manager.pinned_facts_cap
        return f"Remembered: \"{fact}\" ({count}/{cap} fact slots used)"


class ForgetTool(BuiltinTool):
    name = "forget"
    description = (
        "Remove a fact from working memory (Zone 1). Use when a fact is "
        "stale, wrong, or no longer relevant. Frees a memory slot."
    )
    parameters = [
        ToolParameter(
            name="fact_substring",
            type="string",
            description="Substring that uniquely identifies the fact to remove",
        ),
    ]
    is_read_only = False
    requires_confirmation = False
    mutates_state = False
    tool_group = ToolGroup.ADMIN

    _memory_manager: Any = None

    async def execute(self, **kwargs: Any) -> str:
        if self._memory_manager is None:
            return "Error: memory manager not available."

        substring = kwargs.get("fact_substring", "").strip().lower()
        if not substring:
            return "Error: fact_substring cannot be empty."

        removed = self._memory_manager.forget_fact(substring)
        if removed:
            return f"Forgot: \"{removed}\""
        return f"No pinned fact matching '{substring}' found."


def register_memory_tools(
    archive: SessionArchive | None,
    session_id: str | None,
    memory_manager: Any,
) -> list[tuple[ToolDef, Any]]:
    """Create memory tool instances and return (ToolDef, handler) pairs."""
    tools = []

    recall = RecallSessionTool()
    recall._archive = archive
    recall._session_id = session_id
    tools.append((recall.to_tool_def(), recall.execute))

    remember = RememberTool()
    remember._memory_manager = memory_manager
    tools.append((remember.to_tool_def(), remember.execute))

    forget = ForgetTool()
    forget._memory_manager = memory_manager
    tools.append((forget.to_tool_def(), forget.execute))

    return tools
