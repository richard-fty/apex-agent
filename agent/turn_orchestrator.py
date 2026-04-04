"""Turn orchestration separated from tool execution details."""

from __future__ import annotations

import time
from typing import Any, Callable

import litellm

from agent.models import AgentEvent, EventType
from agent.tool_executor import ToolExecutor
from harness.runtime import RuntimeGuard
from harness.token_tracker import extract_usage
from harness.trace import Trace


EventCallback = Callable[[AgentEvent], None]


class TurnOrchestrator:
    """Run a single user turn using session state plus a tool executor."""

    def __init__(self, session: Any, callback: EventCallback, tool_executor: ToolExecutor) -> None:
        self.session = session
        self.callback = callback
        self.tool_executor = tool_executor

    async def execute(self, user_input: str, guard: RuntimeGuard, trace: Trace) -> str:
        step = 0
        assistant_content = ""

        while True:
            limit_error = guard.check()
            if limit_error:
                trace.finish(error=limit_error)
                self.callback(AgentEvent(type=EventType.AGENT_ERROR, step=step, data={"error": limit_error}))
                return assistant_content

            prepared = await self.session.prepare_for_model(user_input)
            fitted_messages = prepared.messages
            tools_schema = prepared.tool_schemas

            self.callback(AgentEvent(
                type=EventType.LLM_CALL_START,
                step=step,
                data={
                    "message_count": len(fitted_messages),
                    "tool_count": len(tools_schema),
                    "loaded_skills": self.session.skill_loader.get_loaded_skill_names(),
                    "retrieval_used": bool(prepared.retrieval and prepared.retrieval.used),
                },
            ))

            llm_start = time.time()
            response = await litellm.acompletion(
                model=self.session.model,
                messages=fitted_messages,
                tools=tools_schema if tools_schema else None,
            )
            llm_duration_ms = (time.time() - llm_start) * 1000
            usage = extract_usage(response)
            trace.add_llm_usage(usage)

            choice = response.choices[0]
            assistant_msg = choice.message
            self.callback(AgentEvent(
                type=EventType.LLM_CALL_END,
                step=step,
                data={
                    "content": assistant_msg.content or "",
                    "has_tool_calls": bool(assistant_msg.tool_calls),
                    "tokens": usage.model_dump(),
                    "duration_ms": round(llm_duration_ms, 1),
                },
            ))
            trace.add_event(AgentEvent(
                type=EventType.LLM_CALL_END,
                step=step,
                data={"tokens": usage.model_dump(), "duration_ms": round(llm_duration_ms, 1)},
            ))

            if not assistant_msg.tool_calls:
                assistant_content = assistant_msg.content or ""
                if assistant_content:
                    self.session.add_assistant_message({"role": "assistant", "content": assistant_content})
                trace.finish(output=assistant_content)
                self.callback(AgentEvent(
                    type=EventType.AGENT_END,
                    step=step,
                    data={
                        "output_preview": assistant_content[:200],
                        "loaded_skills": self.session.skill_loader.get_loaded_skill_names(),
                    },
                ))
                return assistant_content

            assistant_dict: dict[str, Any] = {"role": "assistant"}
            if assistant_msg.content:
                assistant_dict["content"] = assistant_msg.content
            assistant_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in assistant_msg.tool_calls
            ]
            self.session.add_assistant_message(assistant_dict)

            raw_calls = [
                {
                    "id": tc.id,
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in assistant_msg.tool_calls
            ]
            parsed_calls = self.session.dispatch.parse_tool_calls(raw_calls)
            skill_changed = False

            for tool_call in parsed_calls:
                self.callback(AgentEvent(
                    type=EventType.TOOL_CALL_START,
                    step=step,
                    data={"name": tool_call.name, "arguments": tool_call.arguments},
                ))
                tool_start = time.time()
                executed = await self.tool_executor.execute(tool_call)
                tool_duration_ms = (time.time() - tool_start) * 1000
                self.callback(AgentEvent(
                    type=EventType.TOOL_CALL_END,
                    step=step,
                    data={
                        "name": tool_call.name,
                        "success": executed.success,
                        "content_preview": executed.content[:200],
                        "duration_ms": round(tool_duration_ms, 1),
                    },
                ))
                trace.add_event(AgentEvent(
                    type=EventType.TOOL_CALL_END,
                    step=step,
                    data={
                        "name": tool_call.name,
                        "success": executed.success,
                        "duration_ms": round(tool_duration_ms, 1),
                    },
                ))
                self.session.add_tool_message(tool_call.id, tool_call.name, executed.content)
                if tool_call.name in {"load_skill", "unload_skill"}:
                    skill_changed = True

            if skill_changed:
                self.session.rebuild_system_prompt()

            guard.increment_step()
            step += 1
