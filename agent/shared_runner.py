"""Shared event-driven runner for CLI and TUI REPL flows."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, AsyncIterator

import litellm

from agent.models import PermissionAction, TokenUsage
from harness.runtime import RuntimeConfig, RuntimeGuard


_SKILL_MUTATING_TOOLS = {"load_skill", "unload_skill"}


@dataclass
class RunnerEvent:
    """A UI-friendly runtime event emitted during a turn."""

    type: str
    data: dict[str, Any]


class SharedTurnRunner:
    """Run one turn as an event stream, including pause/resume for approvals."""

    def __init__(
        self,
        session_engine: Any,
        access_controller: Any,
        cost_tracker: Any,
        model: str,
        runtime_config: RuntimeConfig,
    ) -> None:
        self.session_engine = session_engine
        self.access_controller = access_controller
        self.cost_tracker = cost_tracker
        self.model = model
        self.runtime_config = runtime_config

        self._current_user_input: str | None = None
        self._guard: RuntimeGuard | None = None
        self._step = 0

    async def start_turn(self, user_input: str) -> AsyncIterator[RunnerEvent]:
        self._current_user_input = user_input
        self._guard = RuntimeGuard(self.runtime_config)
        self._step = 0

        yield RunnerEvent("turn_started", {"user_input": user_input})

        pre_loaded = self.session_engine.pre_load_for_input(user_input)
        for skill_name in pre_loaded:
            yield RunnerEvent("skill_auto_loaded", {"skill_name": skill_name})

        self.session_engine.add_user_message(user_input)
        async for event in self._run_loop():
            yield event

    async def resume_pending(self, action: str) -> AsyncIterator[RunnerEvent]:
        pending = self.access_controller.pending
        if pending is None:
            yield RunnerEvent("error", {"message": "No pending approval"})
            return

        tool_call = pending.tool_call
        resolved = self.access_controller.resolve_pending(action)
        if resolved is None:
            yield RunnerEvent("error", {"message": "Approval request was not resolved"})
            return

        tool_start = time.time()
        if resolved.action == PermissionAction.DENY:
            result_content = f"Access denied: {resolved.reason}"
            result_success = False
            yield RunnerEvent(
                "tool_denied",
                {"name": tool_call.name, "reason": resolved.reason},
            )
        else:
            self.access_controller.record_allow(tool_call.name)
            result = await self.session_engine.dispatch.execute(tool_call)
            result_content = result.content
            result_success = result.success

        tool_ms = (time.time() - tool_start) * 1000
        result_content = self.session_engine.context_mgr.compact_tool_result(result_content)
        self.session_engine.add_tool_message(tool_call.id, tool_call.name, result_content)
        yield RunnerEvent(
            "tool_finished",
            {
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "success": result_success,
                "duration_ms": tool_ms,
                "content": result_content,
            },
        )

        if self._guard is None:
            self._guard = RuntimeGuard(self.runtime_config)
        self._guard.increment_step()
        self._step += 1

        async for event in self._run_loop():
            yield event

    async def _run_loop(self) -> AsyncIterator[RunnerEvent]:
        if self._current_user_input is None:
            yield RunnerEvent("error", {"message": "No active turn"})
            return

        while True:
            if self._guard is None:
                self._guard = RuntimeGuard(self.runtime_config)

            limit_error = self._guard.check()
            if limit_error:
                yield RunnerEvent("error", {"message": limit_error})
                return

            prepared = await self.session_engine.prepare_for_model(self._current_user_input)
            if self._step == 0 and prepared.retrieval and prepared.retrieval.route == "research":
                yield RunnerEvent("research_started", {"query": self._current_user_input})
                evidence = prepared.retrieval.evidence
                if evidence:
                    for stage in evidence.stages:
                        yield RunnerEvent(stage, {})
                    yield RunnerEvent(
                        "evidence_ready",
                        {
                            "items": len(evidence.items),
                            "used_local": evidence.used_local,
                            "used_web": evidence.used_web,
                        },
                    )
            yield RunnerEvent(
                "llm_call_started",
                {
                    "step": self._step,
                    "message_count": len(prepared.messages),
                    "tool_count": len(prepared.tool_schemas),
                },
            )

            llm_start = time.time()
            try:
                response = await litellm.acompletion(
                    model=self.model,
                    messages=prepared.messages,
                    tools=prepared.tool_schemas if prepared.tool_schemas else None,
                    stream=True,
                    stream_options={"include_usage": True},
                )
            except Exception as exc:
                yield RunnerEvent("error", {"message": f"LLM: {exc}"})
                return

            full_content = ""
            tool_calls_raw: list[dict[str, Any]] = []
            usage_data = None
            saw_stream_text = False

            async for chunk in response:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    continue

                if delta.content:
                    saw_stream_text = True
                    full_content += delta.content
                    yield RunnerEvent("token", {"text": delta.content})

                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        while len(tool_calls_raw) <= idx:
                            tool_calls_raw.append({"id": "", "function": {"name": "", "arguments": ""}})
                        if tc_delta.id:
                            tool_calls_raw[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_calls_raw[idx]["function"]["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                tool_calls_raw[idx]["function"]["arguments"] += tc_delta.function.arguments

                if hasattr(chunk, "usage") and chunk.usage:
                    usage_data = chunk.usage

            llm_ms = (time.time() - llm_start) * 1000
            usage = TokenUsage()
            if usage_data:
                usage.prompt_tokens = getattr(usage_data, "prompt_tokens", 0) or 0
                usage.completion_tokens = getattr(usage_data, "completion_tokens", 0) or 0
                usage.total_tokens = usage.prompt_tokens + usage.completion_tokens

            self.cost_tracker.add_step(self._step, usage)
            yield RunnerEvent(
                "usage",
                {
                    "step": self._step,
                    "usage": usage,
                    "duration_ms": llm_ms,
                },
            )

            budget_error = self.cost_tracker.check_budget()
            if budget_error:
                yield RunnerEvent("error", {"message": budget_error})
                return

            if tool_calls_raw and tool_calls_raw[0]["function"]["name"]:
                if full_content:
                    yield RunnerEvent("assistant_note", {"text": full_content})

                assistant_dict: dict[str, Any] = {"role": "assistant"}
                if full_content:
                    assistant_dict["content"] = full_content
                assistant_dict["tool_calls"] = [
                    {"id": tc["id"], "type": "function", "function": tc["function"]}
                    for tc in tool_calls_raw
                ]
                self.session_engine.add_assistant_message(assistant_dict)

                parsed_calls = self.session_engine.dispatch.parse_tool_calls(tool_calls_raw)
                skill_changed = False

                for tool_call in parsed_calls:
                    yield RunnerEvent(
                        "tool_started",
                        {"name": tool_call.name, "arguments": tool_call.arguments},
                    )

                    tool_start = time.time()
                    if (validation_error := self.session_engine.dispatch.validate_call(tool_call)):
                        result_content = self.session_engine.dispatch.retry_prompt(tool_call, validation_error)
                        result_success = False
                    else:
                        tool_def = self.session_engine.dispatch.get_tool_def(tool_call.name)
                        if tool_def is None:
                            result_content = f"Unknown tool: {tool_call.name}"
                            result_success = False
                        else:
                            decision = self.access_controller.evaluate(tool_call, tool_def)
                            if decision.action == PermissionAction.DENY:
                                result_content = f"Access denied: {decision.reason}"
                                result_success = False
                                yield RunnerEvent(
                                    "tool_denied",
                                    {"name": tool_call.name, "reason": decision.reason},
                                )
                            elif decision.action == PermissionAction.ASK:
                                self.access_controller.create_pending(tool_call, decision)
                                yield RunnerEvent(
                                    "approval_requested",
                                    {
                                        "tool_name": tool_call.name,
                                        "reason": decision.reason,
                                        "step": self._step,
                                    },
                                )
                                return
                            else:
                                self.access_controller.record_allow(tool_call.name)
                                result = await self.session_engine.dispatch.execute(tool_call)
                                result_content = result.content
                                result_success = result.success

                    tool_ms = (time.time() - tool_start) * 1000
                    result_content = self.session_engine.context_mgr.compact_tool_result(result_content)
                    self.session_engine.add_tool_message(tool_call.id, tool_call.name, result_content)
                    yield RunnerEvent(
                        "tool_finished",
                        {
                            "name": tool_call.name,
                            "arguments": tool_call.arguments,
                            "success": result_success,
                            "duration_ms": tool_ms,
                            "content": result_content,
                        },
                    )

                    if tool_call.name in _SKILL_MUTATING_TOOLS:
                        skill_changed = True

                if skill_changed:
                    self.session_engine.rebuild_system_prompt()
                    yield RunnerEvent("skills_reloaded", {})

                self._guard.increment_step()
                self._step += 1
                continue

            if full_content and not saw_stream_text:
                yield RunnerEvent("token", {"text": full_content})

            if full_content:
                self.session_engine.add_assistant_message({"role": "assistant", "content": full_content})

            yield RunnerEvent("turn_finished", {"content": full_content})
            return
