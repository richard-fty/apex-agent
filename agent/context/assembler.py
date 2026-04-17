"""Assemble model-ready context from session state and runtime policies.

Injection order in the context window (closest to end = highest attention):

  [START — lowest attention]
    System prompt              (instructions, persona)
    Plan view                  (Zone 1 — task list with statuses)
    Pinned facts               (Zone 1 — extracted/remembered key data)
    Retrieval context          (injected evidence from RAG/web)
  [MIDDLE]
    Compressed history         (Zone 2 — if strategy produces it)
  [END — highest attention]
    Recent turns               (Zone 3 — full-fidelity sliding window)
    Current user message       (maximum attention)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.context.manager import ContextManager
from agent.runtime.tool_dispatch import ToolDispatch
from services.retrieval_policy import RetrievalContext, RetrievalPolicy


@dataclass
class PreparedContext:
    """Context bundle ready for a model call."""

    messages: list[dict[str, Any]]
    tool_schemas: list[dict[str, Any]]
    retrieval: RetrievalContext


class ContextAssembler:
    """Own prompt assembly, retrieval injection, and visible tool surfacing."""

    def __init__(
        self,
        context_manager: ContextManager,
        retrieval_policy: RetrievalPolicy,
        plan_manager: Any | None = None,
    ) -> None:
        self.context_manager = context_manager
        self.retrieval_policy = retrieval_policy
        self.plan_manager = plan_manager

    async def prepare(
        self,
        messages: list[dict[str, Any]],
        user_input: str,
        dispatch: ToolDispatch,
    ) -> PreparedContext:
        retrieval = await self.retrieval_policy.evaluate(user_input)
        tool_schemas = dispatch.to_openai_tools(
            include_runtime_injected=retrieval.should_offer_runtime_tools,
        )
        fitted_messages = await self.context_manager.prepare(messages, tool_schemas)

        # Inject Zone 1 pinned content (plan + facts) after system prompt
        zone_1_content = self._build_zone_1_content()
        if zone_1_content:
            fitted_messages = self._inject_after_system(fitted_messages, zone_1_content)

        if retrieval.injected_message:
            fitted_messages = self._inject_after_system(
                fitted_messages, retrieval.injected_message,
            )

        return PreparedContext(
            messages=fitted_messages,
            tool_schemas=tool_schemas,
            retrieval=retrieval,
        )

    def _build_zone_1_content(self) -> str:
        """Build the pinned Zone 1 content: plan + facts."""
        parts: list[str] = []

        if self.plan_manager is not None:
            plan_view = self.plan_manager.view()
            if "No plan created" not in plan_view:
                parts.append(plan_view)

        pinned_text = self.context_manager.get_pinned_text()
        if pinned_text:
            parts.append(pinned_text)

        return "\n\n".join(parts)

    def _inject_after_system(
        self,
        messages: list[dict[str, Any]],
        content: str,
    ) -> list[dict[str, Any]]:
        """Inject content as a system message right after the main system prompt."""
        system_messages = [msg for msg in messages if msg.get("role") == "system"]
        non_system = [msg for msg in messages if msg.get("role") != "system"]
        return system_messages + [{"role": "system", "content": content}] + non_system
