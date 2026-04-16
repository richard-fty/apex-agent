"""Assemble model-ready context from session state and runtime policies."""

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
    ) -> None:
        self.context_manager = context_manager
        self.retrieval_policy = retrieval_policy

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
        if retrieval.injected_message:
            fitted_messages = self._inject_retrieval_message(
                fitted_messages,
                retrieval.injected_message,
            )
        return PreparedContext(
            messages=fitted_messages,
            tool_schemas=tool_schemas,
            retrieval=retrieval,
        )

    def _inject_retrieval_message(
        self,
        messages: list[dict[str, Any]],
        retrieval_message: str,
    ) -> list[dict[str, Any]]:
        system_messages = [msg for msg in messages if msg.get("role") == "system"]
        non_system = [msg for msg in messages if msg.get("role") != "system"]
        return system_messages + [{"role": "system", "content": retrieval_message}] + non_system
