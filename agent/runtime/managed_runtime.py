"""Managed agent runtime with explicit brain, harness, session, and orchestration seams."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable

import litellm

from agent.core.models import (
    AgentEvent,
    AgentState,
    EventType,
    PermissionAction,
    PendingApproval,
    TokenUsage,
    ToolCall,
)
from agent.session.archive import SessionArchive
from agent.session.store import SessionStore
from config import settings
from agent.runtime.guards import RuntimeConfig, RuntimeGuard
from agent.runtime.token_tracker import extract_usage
from agent.runtime.trace import Trace

logger = logging.getLogger(__name__)

_SKILL_MUTATING_TOOLS = {"load_skill", "unload_skill"}
_PLAN_MUTATING_TOOLS = {"todo_write", "todo_update"}
_MAX_LLM_RETRIES = 3
_RETRYABLE_ERRORS = (
    litellm.RateLimitError,
    litellm.APIConnectionError,
    litellm.Timeout,
    ConnectionError,
    TimeoutError,
)


@dataclass
class ManagedEvent:
    """Unified runtime event for UI streaming and trace mapping."""

    type: str
    data: dict[str, Any]


@dataclass
class SessionRecord:
    """Durable-minded in-memory session record.

    This is intentionally simple for now: it provides a stable seam so the repo
    can move from in-memory state toward a persisted event log later.
    """

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: AgentState = AgentState.IDLE
    events: list[dict[str, Any]] = field(default_factory=list)
    pending_approval: PendingApproval | None = None
    stop_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def append_event(self, event_type: str, **payload: Any) -> None:
        self.events.append({
            "type": event_type,
            "timestamp": time.time(),
            "payload": payload,
        })

    def set_state(self, state: AgentState, *, reason: str | None = None) -> None:
        self.state = state
        if reason:
            self.stop_reason = reason
        self.append_event("state_changed", state=state.value, reason=reason)


class LiteLLMBrain:
    """Brain adapter around LiteLLM."""

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        stream: bool,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "tools": tools if tools else None,
        }
        if stream:
            kwargs["stream"] = True
            kwargs["stream_options"] = {"include_usage": True}
        return await litellm.acompletion(**kwargs)


class ManagedAgentRuntime:
    """Managed runtime that orchestrates the brain, session, tools, and approvals."""

    def __init__(
        self,
        *,
        session_engine: Any,
        model: str,
        runtime_config: RuntimeConfig,
        access_controller: Any | None = None,
        cost_tracker: Any | None = None,
        brain: LiteLLMBrain | None = None,
        session_store: SessionStore | None = None,
        archive: SessionArchive | None = None,
    ) -> None:
        self.session_engine = session_engine
        self.model = model
        self.runtime_config = runtime_config
        self.access_controller = access_controller
        self.cost_tracker = cost_tracker
        self.brain = brain or LiteLLMBrain()
        self.session_store = session_store or SessionStore(settings.session_store_dir)
        self.archive = archive

        self.session = SessionRecord()
        self._current_user_input: str | None = None
        self._guard: RuntimeGuard | None = None
        self._step = 0
        self._active_trace: Trace | None = None
        self.session.metadata = {
            "model": self.model,
            "context_strategy": getattr(self.session_engine, "context_strategy", "truncate"),
        }
        self.session_store.create(
            session_id=self.session.session_id,
            model=self.model,
            context_strategy=self.session.metadata["context_strategy"],
        )
        if self.archive is not None:
            self.archive.create_session(
                session_id=self.session.session_id,
                model=self.model,
                context_strategy=self.session.metadata["context_strategy"],
            )

    async def start_turn(self, user_input: str) -> AsyncIterator[ManagedEvent]:
        self._current_user_input = user_input
        self._guard = RuntimeGuard(self.runtime_config)
        self._step = 0
        self.session.set_state(AgentState.RUNNING)
        self.session.append_event("user_input_received", user_input=user_input)
        self._persist_session()

        yield ManagedEvent("turn_started", {"session_id": self.session.session_id, "user_input": user_input})

        pre_loaded = self.session_engine.pre_load_for_input(user_input)
        for skill_name in pre_loaded:
            self.session.append_event("skill_auto_loaded", skill_name=skill_name)
            yield ManagedEvent("skill_auto_loaded", {"skill_name": skill_name})

        self.session_engine.add_user_message(user_input)
        self.session.append_event("user_message_added", message={"role": "user", "content": user_input})
        self._persist_session()
        async for event in self._run_loop():
            yield event

    def cancel(self) -> None:
        if self._guard is not None:
            self._guard.cancel()
        self.session.set_state(AgentState.CANCELLED, reason="Run cancelled by user")
        self._persist_session()

    async def resume_pending(self, action: str) -> AsyncIterator[ManagedEvent]:
        if self.access_controller is None or self.access_controller.pending is None:
            yield ManagedEvent("error", {"message": "No pending approval"})
            return

        pending = self.access_controller.pending
        self.session.pending_approval = pending
        self.session.append_event("approval_resolved", action=action, tool_name=pending.tool_call.name)
        resolved = self.access_controller.resolve_pending(action)
        self.session.pending_approval = None
        self._persist_session()
        if resolved is None:
            yield ManagedEvent("error", {"message": "Approval request was not resolved"})
            return

        if self._active_trace is not None:
            self._active_trace.record_approval_decision(
                step=self._step,
                tool_name=pending.tool_call.name,
                action=resolved.action.value,
                reason=resolved.reason,
                rule_source=resolved.rule_source,
                resolved_by=action,
            )

        tool_call = pending.tool_call
        tool_ms, result_content, result_success = await self._execute_resolved_tool_call(tool_call, resolved)
        self.session_engine.add_tool_message(tool_call.id, tool_call.name, result_content)
        self.session.append_event(
            "tool_message_added",
            message={
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "content": result_content,
            },
        )
        self._persist_session()
        yield ManagedEvent(
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
        self.session.set_state(AgentState.RUNNING)
        self._persist_session()

        async for event in self._run_loop():
            yield event

    async def run_to_completion(
        self,
        *,
        user_input: str,
        trace: Trace,
        callback: Callable[[AgentEvent], None] | None = None,
    ) -> str:
        callback = callback or (lambda _: None)
        self._active_trace = trace
        final_content = ""

        async for event in self.start_turn(user_input):
            final_content = self._map_event_to_trace(event, trace, callback, final_content)
            if event.type == "approval_requested":
                message = (
                    f"Approval required for tool '{event.data['tool_name']}': "
                    f"{event.data['reason']}"
                )
                self.session.set_state(AgentState.WAITING_APPROVAL, reason=message)
                self._persist_session()
                trace.finish(error=message, stop_reason=message)
                callback(AgentEvent(type=EventType.AGENT_ERROR, step=self._step, data={"error": message}))
                return final_content
            if event.type == "turn_finished":
                return event.data.get("content", final_content)
            if event.type == "error":
                error = event.data["message"]
                self._persist_session()
                trace.finish(error=error, stop_reason=self.session.stop_reason or error)
                callback(AgentEvent(type=EventType.AGENT_ERROR, step=self._step, data={"error": error}))
                return final_content

        return final_content

    async def _run_loop(self) -> AsyncIterator[ManagedEvent]:
        if self._current_user_input is None:
            yield ManagedEvent("error", {"message": "No active turn"})
            return

        while True:
            if self._guard is None:
                self._guard = RuntimeGuard(self.runtime_config)

            limit_error = self._guard.check()
            if limit_error:
                state = AgentState.CANCELLED if "cancelled" in limit_error.lower() else AgentState.FAILED
                self.session.set_state(state, reason=limit_error)
                self._persist_session()
                yield ManagedEvent("error", {"message": limit_error})
                return

            prepared = await self.session_engine.prepare_for_model(self._current_user_input)
            retrieval = getattr(prepared, "retrieval", None)
            retrieval_used = bool(retrieval and getattr(retrieval, "used", False))
            self.session.append_event(
                "context_prepared",
                step=self._step,
                message_count=len(prepared.messages),
                tool_count=len(prepared.tool_schemas),
                retrieval_used=retrieval_used,
            )
            if self._active_trace is not None and retrieval is not None:
                evidence = getattr(retrieval, "evidence", None)
                items = getattr(evidence, "items", []) if evidence else []
                self._active_trace.record_retrieval_injection(
                    step=self._step,
                    route=getattr(retrieval, "route", "default"),
                    used=retrieval_used,
                    item_count=len(items),
                    used_local=bool(getattr(evidence, "used_local", False)) if evidence else False,
                    used_web=bool(getattr(evidence, "used_web", False)) if evidence else False,
                )
            if self._step == 0 and retrieval and getattr(retrieval, "route", None) == "research":
                yield ManagedEvent("research_started", {"query": self._current_user_input})
                evidence = prepared.retrieval.evidence
                if evidence:
                    for stage in evidence.stages:
                        yield ManagedEvent(stage, {})
                    yield ManagedEvent(
                        "evidence_ready",
                        {
                            "items": len(evidence.items),
                            "used_local": evidence.used_local,
                            "used_web": evidence.used_web,
                        },
                    )

            yield ManagedEvent(
                "llm_call_started",
                {
                    "step": self._step,
                    "message_count": len(prepared.messages),
                    "tool_count": len(prepared.tool_schemas),
                },
            )

            llm_start = time.time()
            response = None
            last_error: Exception | None = None
            for attempt in range(_MAX_LLM_RETRIES):
                try:
                    response = await self.brain.complete(
                        model=self.model,
                        messages=prepared.messages,
                        tools=prepared.tool_schemas,
                        stream=True,
                    )
                    break
                except _RETRYABLE_ERRORS as exc:
                    last_error = exc
                    if attempt < _MAX_LLM_RETRIES - 1:
                        backoff = 2 ** attempt
                        self.session.append_event(
                            "api_retry",
                            attempt=attempt + 1,
                            error=str(exc),
                            backoff_s=backoff,
                        )
                        self._persist_session()
                        logger.warning("LLM retry %d/%d after %s (backoff %ds)",
                                       attempt + 1, _MAX_LLM_RETRIES, type(exc).__name__, backoff)
                        yield ManagedEvent("api_retry", {
                            "attempt": attempt + 1,
                            "backoff_s": backoff,
                            "error": str(exc),
                        })
                        await asyncio.sleep(backoff)
                except Exception as exc:
                    last_error = exc
                    break  # non-retryable error, fail immediately

            if response is None:
                message = f"LLM: {last_error}"
                self.session.set_state(AgentState.FAILED, reason=message)
                self._persist_session()
                yield ManagedEvent("error", {"message": message})
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
                    yield ManagedEvent("token", {"text": delta.content})

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
            usage = extract_usage(type("Response", (), {"usage": usage_data})()) if usage_data else TokenUsage()
            if self.cost_tracker is not None:
                self.cost_tracker.add_step(self._step, usage)
                budget_error = self.cost_tracker.check_budget()
                if budget_error:
                    self.session.set_state(AgentState.FAILED, reason=budget_error)
                    self._persist_session()
                    yield ManagedEvent("usage", {"step": self._step, "usage": usage, "duration_ms": llm_ms})
                    yield ManagedEvent("error", {"message": budget_error})
                    return

            yield ManagedEvent(
                "usage",
                {
                    "step": self._step,
                    "usage": usage,
                    "duration_ms": llm_ms,
                },
            )

            if tool_calls_raw and tool_calls_raw[0]["function"]["name"]:
                if full_content:
                    yield ManagedEvent("assistant_note", {"text": full_content})

                assistant_dict: dict[str, Any] = {"role": "assistant"}
                if full_content:
                    assistant_dict["content"] = full_content
                assistant_dict["tool_calls"] = [
                    {"id": tc["id"], "type": "function", "function": tc["function"]}
                    for tc in tool_calls_raw
                ]
                self.session_engine.add_assistant_message(assistant_dict)
                self.session.append_event("assistant_message_added", message=assistant_dict, has_tool_calls=True)
                self._persist_session()

                parsed_calls = self.session_engine.dispatch.parse_tool_calls(tool_calls_raw)
                skill_changed = False
                plan_changed = False

                for tool_call in parsed_calls:
                    async for event in self._handle_tool_call(tool_call):
                        yield event
                        if event.type == "approval_requested":
                            return

                    if tool_call.name in _SKILL_MUTATING_TOOLS:
                        skill_changed = True
                    if tool_call.name in _PLAN_MUTATING_TOOLS:
                        plan_changed = True

                if skill_changed:
                    self.session_engine.rebuild_system_prompt()
                    self.session.append_event("system_prompt_rebuilt")
                    self._persist_session()
                    yield ManagedEvent("skills_reloaded", {})

                if plan_changed:
                    pm = getattr(self.session_engine, "plan_manager", None)
                    if pm is not None:
                        event_type = "plan_created" if pm.create_count > 0 else "plan_task_updated"
                        self.session.append_event(event_type, **pm.to_event_payload())
                        self._persist_session()
                        yield ManagedEvent("plan_updated", pm.to_event_payload())

                self._guard.increment_step()
                self._step += 1
                continue

            if full_content and not saw_stream_text:
                yield ManagedEvent("token", {"text": full_content})

            if full_content:
                self.session_engine.add_assistant_message({"role": "assistant", "content": full_content})
                self.session.append_event(
                    "assistant_message_added",
                    message={"role": "assistant", "content": full_content},
                    has_tool_calls=False,
                )

            self.session.set_state(AgentState.COMPLETED, reason="completed")
            self._persist_session()
            yield ManagedEvent("turn_finished", {"content": full_content})
            return

    async def _handle_tool_call(self, tool_call: ToolCall) -> AsyncIterator[ManagedEvent]:
        yield ManagedEvent("tool_started", {"name": tool_call.name, "arguments": tool_call.arguments})
        self.session.append_event("tool_started", step=self._step, tool_name=tool_call.name, arguments=tool_call.arguments)
        self._persist_session()

        tool_start = time.time()
        if (validation_error := self.session_engine.dispatch.validate_call(tool_call)):
            result_content = self.session_engine.dispatch.retry_prompt(tool_call, validation_error)
            result_success = False
            if self._active_trace is not None:
                self._active_trace.record_recovery_event(
                    step=self._step,
                    kind="malformed_arguments",
                    tool_name=tool_call.name,
                    detail=validation_error,
                )
        else:
            tool_def = self.session_engine.dispatch.get_tool_def(tool_call.name)
            if tool_def is None:
                result_content = f"Unknown tool: {tool_call.name}"
                result_success = False
                if self._active_trace is not None:
                    self._active_trace.record_recovery_event(
                        step=self._step,
                        kind="unknown_tool",
                        tool_name=tool_call.name,
                        detail=result_content,
                    )
            elif self.access_controller is not None:
                decision = self.access_controller.evaluate(tool_call, tool_def)
                if self._active_trace is not None:
                    self._active_trace.record_approval_decision(
                        step=self._step,
                        tool_name=tool_call.name,
                        action=decision.action.value,
                        reason=decision.reason,
                        rule_source=decision.rule_source,
                    )
                if decision.action == PermissionAction.DENY:
                    result_content = f"Access denied: {decision.reason}"
                    result_success = False
                    self.session.append_event("tool_denied", tool_name=tool_call.name, reason=decision.reason)
                    self._persist_session()
                    yield ManagedEvent("tool_denied", {"name": tool_call.name, "reason": decision.reason})
                elif decision.action == PermissionAction.ASK:
                    pending = self.access_controller.create_pending(tool_call, decision)
                    self.session.pending_approval = pending
                    self.session.set_state(AgentState.WAITING_APPROVAL, reason=decision.reason)
                    self.session.append_event("approval_requested", tool_name=tool_call.name, reason=decision.reason)
                    self._persist_session()
                    yield ManagedEvent(
                        "approval_requested",
                        {"tool_name": tool_call.name, "reason": decision.reason, "step": self._step},
                    )
                    return
                else:
                    tool_ms, result_content, result_success = await self._execute_allowed_tool_call(tool_call)
                    if not result_success and self._active_trace is not None:
                        self._active_trace.record_recovery_event(
                            step=self._step,
                            kind="tool_execution_failed",
                            tool_name=tool_call.name,
                            detail=result_content[:200],
                        )
                    self.session_engine.add_tool_message(tool_call.id, tool_call.name, result_content)
                    self.session.append_event(
                        "tool_finished",
                        tool_name=tool_call.name,
                        success=result_success,
                        duration_ms=tool_ms,
                        content=result_content,
                    )
                    self.session.append_event(
                        "tool_message_added",
                        message={
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": result_content,
                        },
                    )
                    self._persist_session()
                    yield ManagedEvent(
                        "tool_finished",
                        {
                            "name": tool_call.name,
                            "arguments": tool_call.arguments,
                            "success": result_success,
                            "duration_ms": tool_ms,
                            "content": result_content,
                        },
                    )
                    return
            else:
                tool_ms, result_content, result_success = await self._execute_tool_call(tool_call)
                if not result_success and self._active_trace is not None:
                    self._active_trace.record_recovery_event(
                        step=self._step,
                        kind="tool_execution_failed",
                        tool_name=tool_call.name,
                        detail=result_content[:200],
                    )
                self.session_engine.add_tool_message(tool_call.id, tool_call.name, result_content)
                self.session.append_event(
                    "tool_finished",
                    tool_name=tool_call.name,
                    success=result_success,
                    duration_ms=tool_ms,
                    content=result_content,
                )
                self.session.append_event(
                    "tool_message_added",
                    message={
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": result_content,
                    },
                )
                self._persist_session()
                yield ManagedEvent(
                    "tool_finished",
                    {
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                        "success": result_success,
                        "duration_ms": tool_ms,
                        "content": result_content,
                    },
                )
                return

        tool_ms = (time.time() - tool_start) * 1000
        result_content = self.session_engine.context_mgr.compact_tool_result(result_content)
        self.session_engine.add_tool_message(tool_call.id, tool_call.name, result_content)
        self.session.append_event(
            "tool_finished",
            tool_name=tool_call.name,
            success=result_success,
            duration_ms=tool_ms,
            content=result_content,
        )
        self.session.append_event(
            "tool_message_added",
            message={
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "content": result_content,
            },
        )
        self._persist_session()
        yield ManagedEvent(
            "tool_finished",
            {
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "success": result_success,
                "duration_ms": tool_ms,
                "content": result_content,
            },
        )

    async def _execute_allowed_tool_call(self, tool_call: ToolCall) -> tuple[float, str, bool]:
        self.access_controller.record_allow(tool_call.name)
        return await self._execute_tool_call(tool_call)

    async def _execute_resolved_tool_call(self, tool_call: ToolCall, decision: Any) -> tuple[float, str, bool]:
        tool_start = time.time()
        if decision.action == PermissionAction.DENY:
            result_content = f"Access denied: {decision.reason}"
            result_success = False
        else:
            self.access_controller.record_allow(tool_call.name)
            _, result_content, result_success = await self._execute_tool_call(tool_call)
        tool_ms = (time.time() - tool_start) * 1000
        result_content = self.session_engine.context_mgr.compact_tool_result(result_content)
        return tool_ms, result_content, result_success

    async def _execute_tool_call(self, tool_call: ToolCall) -> tuple[float, str, bool]:
        tool_start = time.time()
        result = await self.session_engine.dispatch.execute(tool_call)
        tool_ms = (time.time() - tool_start) * 1000
        result_content = self.session_engine.context_mgr.compact_tool_result(result.content)
        return tool_ms, result_content, result.success

    def _map_event_to_trace(
        self,
        event: ManagedEvent,
        trace: Trace,
        callback: Callable[[AgentEvent], None],
        final_content: str,
    ) -> str:
        if event.type == "llm_call_started":
            callback(AgentEvent(type=EventType.LLM_CALL_START, step=self._step, data=event.data))
        elif event.type == "usage":
            usage = event.data["usage"]
            trace.add_llm_usage(usage)
            trace.add_event(AgentEvent(
                type=EventType.LLM_CALL_END,
                step=self._step,
                data={"tokens": usage.model_dump(), "duration_ms": round(event.data["duration_ms"], 1)},
            ))
            callback(AgentEvent(
                type=EventType.LLM_CALL_END,
                step=self._step,
                data={"tokens": usage.model_dump(), "duration_ms": round(event.data["duration_ms"], 1)},
            ))
        elif event.type == "tool_started":
            callback(AgentEvent(type=EventType.TOOL_CALL_START, step=self._step, data=event.data))
        elif event.type == "tool_finished":
            trace.add_event(AgentEvent(
                type=EventType.TOOL_CALL_END,
                step=self._step,
                data={
                    "name": event.data["name"],
                    "success": event.data["success"],
                    "duration_ms": round(event.data["duration_ms"], 1),
                },
            ))
            callback(AgentEvent(
                type=EventType.TOOL_CALL_END,
                step=self._step,
                data={
                    "name": event.data["name"],
                    "success": event.data["success"],
                    "content_preview": event.data["content"][:200],
                    "duration_ms": round(event.data["duration_ms"], 1),
                },
            ))
        elif event.type == "turn_finished":
            final_content = event.data.get("content", "")
            trace.finish(output=final_content, stop_reason=self.session.stop_reason or "completed")
            callback(AgentEvent(
                type=EventType.AGENT_END,
                step=self._step,
                data={"output_preview": final_content[:200]},
            ))
        return final_content

    def _persist_session(self) -> None:
        self.session_store.update_state(
            self.session.session_id,
            state=self.session.state,
            stop_reason=self.session.stop_reason,
            pending_approval=self.session.pending_approval.model_dump() if self.session.pending_approval else None,
            metadata=self.session.metadata,
            events=self.session.events,
        )
        # Dual-write: also emit the latest event to the SQLite archive
        if self.archive is not None and self.session.events:
            latest = self.session.events[-1]
            try:
                self.archive.emit_event(
                    self.session.session_id,
                    latest["type"],
                    latest.get("payload", {}),
                )
            except Exception:
                logger.debug("Archive write failed (non-fatal)", exc_info=True)
