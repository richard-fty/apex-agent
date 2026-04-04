"""Session-level orchestration shared across loop, CLI, and TUI."""

from __future__ import annotations

from typing import Any

from agent.context.manager import ContextManager
from agent.context_assembler import ContextAssembler, PreparedContext
from agent.prompts import build_system_prompt
from agent.skill_loader import SkillLoader
from agent.tool_dispatch import ToolDispatch
from config import settings
from services.retrieval_policy import RetrievalContext, RetrievalPolicy
from tools.base import get_all_builtin_tools
from tools.skill_meta import SkillMetaTools


class SessionEngine:
    """Manage session state, tool surfaces, messages, and retrieval context."""

    def __init__(self, model: str, context_strategy: str) -> None:
        self.model = model
        self.context_strategy = context_strategy
        self.dispatch = ToolDispatch()
        for tool in get_all_builtin_tools():
            self.dispatch.register(tool.to_tool_def(), tool.execute)

        self.skill_loader = SkillLoader(self.dispatch)
        self.skill_loader.discover()

        meta_tools = SkillMetaTools(self.skill_loader)
        for tool_def, handler in meta_tools.get_tool_pairs():
            self.dispatch.register(tool_def, handler)

        self.context_mgr = ContextManager(strategy_name=context_strategy, model=model)
        self.retrieval_policy = RetrievalPolicy()
        self.context_assembler = ContextAssembler(self.context_mgr, self.retrieval_policy)
        self.messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": build_system_prompt(
                    self.skill_loader,
                    response_language=settings.response_language,
                ),
            }
        ]
        self.last_retrieval_context: RetrievalContext | None = None

    def pre_load_for_input(self, user_input: str) -> list[str]:
        loaded = self.skill_loader.pre_load_by_intent(user_input)
        if loaded:
            self.rebuild_system_prompt()
        return loaded

    def rebuild_system_prompt(self) -> None:
        self.messages[0] = {
            "role": "system",
            "content": build_system_prompt(
                self.skill_loader,
                response_language=settings.response_language,
            ),
        }

    def add_user_message(self, user_input: str) -> None:
        self.messages.append({"role": "user", "content": user_input})

    def add_assistant_message(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    def add_tool_message(self, tool_call_id: str, name: str, content: str) -> None:
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": name,
            "content": content,
        })

    async def prepare_for_model(self, user_input: str) -> PreparedContext:
        prepared = await self.context_assembler.prepare(self.messages, user_input, self.dispatch)
        self.last_retrieval_context = prepared.retrieval
        return prepared
