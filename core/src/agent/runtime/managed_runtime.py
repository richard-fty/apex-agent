"""Managed agent runtime with explicit brain, harness, session, and orchestration seams."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable
from urllib.parse import urlparse

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
from agent.artifacts import ArtifactStore, FilesystemArtifactStore
from agent.events import (
    ApprovalRequested,
    ApprovalResolved,
    AssistantNote,
    AssistantToken,
    EducationDisclaimer,
    ErrorEvent,
    EventBus,
    InMemoryEventBus,
    PlanStep,
    PlanUpdated,
    SessionCreated,
    SkillAutoLoaded,
    StreamEnd,
    ToolDenied,
    ToolFinished,
    ToolStarted,
    TurnFinished,
    TurnStarted,
    UsageEvent,
)
from agent.policy.education_compliance import DISCLAIMER_MESSAGE, enforce_education_content
from agent.events.schema import AgentEvent as TypedAgentEvent
from agent.runtime.tool_context import ToolContext, tool_context_scope
from agent.session.archive import SessionArchive
from agent.runtime.guards import RuntimeConfig, RuntimeGuard
from agent.runtime.sandbox import (
    BaseSandbox,
    create_session_sandbox,
    get_sandbox_resources,
    sandbox_context,
)
from agent.runtime.tracking import extract_usage
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


def _plan_payload_to_steps(payload: dict[str, Any]) -> list[PlanStep]:
    """Map plan_manager.to_event_payload() into typed PlanStep list.

    Accepts either `{"tasks": [{"id", "text", "status"}, ...]}` or a flat list.
    """
    items = payload.get("tasks") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    out: list[PlanStep] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        status = _normalize_todo_status(item.get("status", "pending"))
        out.append(
            PlanStep(
                id=str(item.get("id", i)),
                text=str(item.get("text", item.get("title", ""))),
                status=status,
            )
        )
    return out


def _normalize_todo_status(value: Any) -> str:
    raw = str(value or "pending")
    if raw in {"pending", "in_progress", "completed", "failed"}:
        return raw
    if raw == "done":
        return "completed"
    if raw == "blocked":
        return "pending"
    if raw in {"cancelled", "skipped"}:
        return "failed"
    return "pending"


@dataclass
class ManagedEvent:
    """Unified runtime event for UI streaming and trace mapping."""

    type: str
    data: dict[str, Any]


@dataclass
class SessionRecord:
    """Durable session record that persists run-scoped execution state.

    All state that must survive crash recovery or a harness restart lives here,
    not as bare instance variables on the runtime.
    """

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: AgentState = AgentState.IDLE
    events: list[dict[str, Any]] = field(default_factory=list)
    pending_approval: PendingApproval | None = None
    stop_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    step: int = 0
    current_user_input: str | None = None
    turn_id: str | None = None  # set at start_turn, reused during resume_pending

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
        archive: SessionArchive | None = None,
        session_id: str | None = None,
        sandbox: BaseSandbox | None = None,
        event_bus: EventBus | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self.session_engine = session_engine
        self.model = model
        self.runtime_config = runtime_config
        self.access_controller = access_controller
        self.cost_tracker = cost_tracker
        self.brain = brain or LiteLLMBrain()
        self.archive = archive or SessionArchive()
        self.event_bus: EventBus = event_bus or InMemoryEventBus()
        self.artifact_store: ArtifactStore = artifact_store or FilesystemArtifactStore()

        self.session = SessionRecord(session_id=session_id or str(uuid.uuid4()))
        self.sandbox = sandbox or create_session_sandbox(session_id=self.session.session_id)
        self._sandbox_provisioned = False
        self.session.metadata = {
            "model": self.model,
            "context_strategy": getattr(self.session_engine, "context_strategy", "truncate"),
            "sandbox_backend": type(self.sandbox).__name__,
        }
        if self.archive is not None:
            self.archive.create_session(
                session_id=self.session.session_id,
                model=self.model,
                context_strategy=self.session.metadata["context_strategy"],
                metadata=self._archive_metadata_snapshot(),
            )

    # ---- Event bus helpers ----------------------------------------------

    def _bus_kwargs(self) -> dict[str, Any]:
        """Common kwargs for every typed AgentEvent we publish."""
        return {
            "session_id": self.session.session_id,
            "turn_id": self.session.turn_id,
        }

    async def _publish(self, event: TypedAgentEvent) -> None:
        """Publish a typed AgentEvent to the bus (non-fatal on failure)."""
        try:
            await self.event_bus.publish(self.session.session_id, event)
        except Exception:
            logger.debug("Event bus publish failed (non-fatal)", exc_info=True)

    async def _emit_stream_end(
        self,
        final_state: str,
        reason: str | None = None,
    ) -> None:
        """Sentinel: consumers close their subscription on this event."""
        await self._publish(
            StreamEnd(
                **self._bus_kwargs(),
                final_state=final_state,  # type: ignore[arg-type]
                reason=reason,
            )
        )

    async def start_turn(
        self,
        user_input: str,
        *,
        guard: RuntimeGuard,
        trace: Trace | None = None,
    ) -> AsyncIterator[ManagedEvent]:
        self.session.current_user_input = user_input
        self.session.step = 0
        self.session.turn_id = str(uuid.uuid4())
        self._set_cancel_requested(False)
        self.session.metadata["education_scope_used"] = False
        self.session.metadata["education_disclaimer_emitted"] = False
        self.session.set_state(AgentState.RUNNING)
        self.session.append_event("user_input_received", user_input=user_input)
        self._persist_session()

        await self._publish(TurnStarted(**self._bus_kwargs(), user_input=user_input))
        yield ManagedEvent("turn_started", {"session_id": self.session.session_id, "user_input": user_input})

        pre_loaded = self.session_engine.pre_load_for_input(user_input)
        for skill_name in pre_loaded:
            self.session.append_event("skill_auto_loaded", skill_name=skill_name)
            await self._publish(SkillAutoLoaded(**self._bus_kwargs(), skill_name=skill_name))
            yield ManagedEvent("skill_auto_loaded", {"skill_name": skill_name})

        self.session_engine.add_user_message(user_input)
        self.session.append_event("user_message_added", message={"role": "user", "content": user_input})
        self._persist_session()
        async for event in self._run_loop(guard=guard, trace=trace):
            yield event

    def cancel(self) -> None:
        self._set_cancel_requested(True)
        self.session.set_state(AgentState.CANCELLED, reason="Run cancelled by user")
        self._persist_session()

    async def close(self) -> None:
        if self._sandbox_provisioned:
            await self.sandbox.destroy()
            self._sandbox_provisioned = False

    async def resume_pending(
        self,
        action: str,
        *,
        guard: RuntimeGuard,
        trace: Trace | None = None,
    ) -> AsyncIterator[ManagedEvent]:
        if self.access_controller is None or self.access_controller.pending is None:
            await self._publish(ErrorEvent(**self._bus_kwargs(), message="No pending approval"))
            await self._emit_stream_end("failed", reason="No pending approval")
            yield ManagedEvent("error", {"message": "No pending approval"})
            return

        pending = self.access_controller.pending
        self.session.pending_approval = pending
        # Flip to RUNNING before the first persist so archive consumers don't
        # see the prior WAITING_APPROVAL state and treat the resume as terminal.
        self._set_cancel_requested(False)
        self.session.set_state(AgentState.RUNNING)
        self.session.append_event("approval_resolved", action=action, tool_name=pending.tool_call.name)
        await self._publish(
            ApprovalResolved(
                **self._bus_kwargs(),
                tool_name=pending.tool_call.name,
                action=action,  # type: ignore[arg-type]
            )
        )
        resolved = self.access_controller.resolve_pending(action)
        self.session.pending_approval = None
        self._persist_session()
        if resolved is None:
            await self._publish(ErrorEvent(**self._bus_kwargs(), message="Approval request was not resolved"))
            await self._emit_stream_end("failed", reason="Approval request was not resolved")
            yield ManagedEvent("error", {"message": "Approval request was not resolved"})
            return

        if trace is not None:
            trace.record_approval_decision(
                step=self.session.step,
                tool_name=pending.tool_call.name,
                action=resolved.action.value,
                reason=resolved.reason,
                rule_source=resolved.rule_source,
                resolved_by=action,
            )

        tool_call = pending.tool_call
        tool_ms, result_content, result_success = await self._execute_resolved_tool_call(tool_call, resolved)
        search_results = self._extract_search_results(tool_name=tool_call.name, content=result_content)
        self.session_engine.add_tool_message(tool_call.id, tool_call.name, result_content)
        self.session.append_event(
            "tool_finished",
            tool_name=tool_call.name,
            arguments=tool_call.arguments,
            success=result_success,
            duration_ms=tool_ms,
            content=result_content,
            search_results=search_results,
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
        await self._publish(
            ToolFinished(
                **self._bus_kwargs(),
                step=self.session.step,
                name=tool_call.name,
                arguments=tool_call.arguments,
                success=result_success,
                duration_ms=tool_ms,
                content=result_content,
                search_results=search_results,
            )
        )
        yield ManagedEvent(
            "tool_finished",
            {
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "success": result_success,
                "duration_ms": tool_ms,
                "content": result_content,
                "search_results": search_results,
            },
        )

        guard.increment_step()
        self.session.step += 1
        self._persist_session()

        async for event in self._run_loop(guard=guard, trace=trace):
            yield event

    async def run_to_completion(
        self,
        *,
        user_input: str,
        guard: RuntimeGuard,
        trace: Trace,
        callback: Callable[[AgentEvent], None] | None = None,
    ) -> str:
        callback = callback or (lambda _: None)
        final_content = ""

        async for event in self.start_turn(user_input, guard=guard, trace=trace):
            final_content = self._map_event_to_trace(event, trace, callback, final_content)
            if event.type == "approval_requested":
                message = (
                    f"Approval required for tool '{event.data['tool_name']}': "
                    f"{event.data['reason']}"
                )
                self.session.set_state(AgentState.WAITING_APPROVAL, reason=message)
                self._persist_session()
                trace.finish(error=message, stop_reason=message)
                callback(AgentEvent(type=EventType.AGENT_ERROR, step=self.session.step, data={"error": message}))
                return final_content
            if event.type == "turn_finished":
                return event.data.get("content", final_content)
            if event.type == "error":
                error = event.data["message"]
                self._persist_session()
                trace.finish(error=error, stop_reason=self.session.stop_reason or error)
                callback(AgentEvent(type=EventType.AGENT_ERROR, step=self.session.step, data={"error": error}))
                return final_content

        return final_content

    async def _run_loop(
        self,
        *,
        guard: RuntimeGuard,
        trace: Trace | None = None,
    ) -> AsyncIterator[ManagedEvent]:
        if self.session.current_user_input is None:
            await self._publish(ErrorEvent(**self._bus_kwargs(), message="No active turn"))
            await self._emit_stream_end("failed", reason="No active turn")
            yield ManagedEvent("error", {"message": "No active turn"})
            return

        while True:
            limit_error = self._check_runtime_limits(guard)
            if limit_error:
                state = AgentState.CANCELLED if "cancelled" in limit_error.lower() else AgentState.FAILED
                self.session.set_state(state, reason=limit_error)
                self.session.append_event("error", message=limit_error)
                self._persist_session()
                await self.close()
                await self._publish(ErrorEvent(**self._bus_kwargs(), message=limit_error))
                await self._emit_stream_end(
                    "cancelled" if state == AgentState.CANCELLED else "failed",
                    reason=limit_error,
                )
                yield ManagedEvent("error", {"message": limit_error})
                return

            prepared = await self.session_engine.prepare_for_model(self.session.current_user_input)
            retrieval = getattr(prepared, "retrieval", None)
            retrieval_used = bool(retrieval and getattr(retrieval, "used", False))
            self.session.append_event(
                "context_prepared",
                step=self.session.step,
                message_count=len(prepared.messages),
                tool_count=len(prepared.tool_schemas),
                retrieval_used=retrieval_used,
            )
            if trace is not None and retrieval is not None:
                evidence = getattr(retrieval, "evidence", None)
                items = getattr(evidence, "items", []) if evidence else []
                trace.record_retrieval_injection(
                    step=self.session.step,
                    route=getattr(retrieval, "route", "default"),
                    used=retrieval_used,
                    item_count=len(items),
                    used_local=bool(getattr(evidence, "used_local", False)) if evidence else False,
                    used_web=bool(getattr(evidence, "used_web", False)) if evidence else False,
                )
            if self.session.step == 0 and retrieval and getattr(retrieval, "route", None) == "research":
                yield ManagedEvent("research_started", {"query": self.session.current_user_input})
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
                    "step": self.session.step,
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
                self.session.append_event("error", message=message)
                self._persist_session()
                await self.close()
                await self._publish(ErrorEvent(**self._bus_kwargs(), message=message))
                await self._emit_stream_end("failed", reason=message)
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
                    await self._publish(AssistantToken(**self._bus_kwargs(), text=delta.content))
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
                self.cost_tracker.add_step(self.session.step, usage)
                budget_error = self.cost_tracker.check_budget()
                if budget_error:
                    self.session.set_state(AgentState.FAILED, reason=budget_error)
                    self.session.append_event(
                        "usage",
                        step=self.session.step,
                        usage=usage.model_dump(),
                        duration_ms=llm_ms,
                    )
                    self.session.append_event("error", message=budget_error)
                    self._persist_session()
                    await self.close()
                    await self._publish(
                        UsageEvent(
                            **self._bus_kwargs(),
                            step=self.session.step,
                            usage=usage,
                            duration_ms=llm_ms,
                        )
                    )
                    await self._publish(ErrorEvent(**self._bus_kwargs(), message=budget_error))
                    await self._emit_stream_end("failed", reason=budget_error)
                    yield ManagedEvent("usage", {"step": self.session.step, "usage": usage, "duration_ms": llm_ms})
                    yield ManagedEvent("error", {"message": budget_error})
                    return

            self.session.append_event(
                "usage",
                step=self.session.step,
                usage=usage.model_dump(),
                duration_ms=llm_ms,
            )
            self._persist_session()
            await self._publish(
                UsageEvent(
                    **self._bus_kwargs(),
                    step=self.session.step,
                    usage=usage,
                    duration_ms=llm_ms,
                )
            )
            yield ManagedEvent(
                "usage",
                {
                    "step": self.session.step,
                    "usage": usage,
                    "duration_ms": llm_ms,
                },
            )

            if tool_calls_raw and tool_calls_raw[0]["function"]["name"]:
                if full_content:
                    self.session.append_event("assistant_note", text=full_content)
                    self._persist_session()
                    await self._publish(AssistantNote(**self._bus_kwargs(), text=full_content))
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
                    async for event in self._handle_tool_call(tool_call, trace=trace):
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
                        payload = pm.to_event_payload()
                        self.session.append_event(event_type, **payload)
                        self._persist_session()
                        plan_steps = _plan_payload_to_steps(payload)
                        await self._publish(PlanUpdated(**self._bus_kwargs(), steps=plan_steps))
                        yield ManagedEvent("plan_updated", payload)

                guard.increment_step()
                self.session.step += 1
                continue

            if full_content and not saw_stream_text:
                yield ManagedEvent("token", {"text": full_content})

            if self._education_scope_used():
                full_content, _ = enforce_education_content(full_content)

            if full_content:
                self.session_engine.add_assistant_message({"role": "assistant", "content": full_content})
                self.session.append_event(
                    "assistant_message_added",
                    message={"role": "assistant", "content": full_content},
                    has_tool_calls=False,
                )

            self.session.set_state(AgentState.COMPLETED, reason="completed")
            self.session.append_event("turn_finished", content=full_content)
            self._persist_session()
            await self.close()
            await self._publish(TurnFinished(**self._bus_kwargs(), content=full_content))
            await self._emit_stream_end("completed")
            yield ManagedEvent("turn_finished", {"content": full_content})
            return

    async def _handle_tool_call(
        self,
        tool_call: ToolCall,
        *,
        trace: Trace | None = None,
    ) -> AsyncIterator[ManagedEvent]:
        await self._publish(
            ToolStarted(
                **self._bus_kwargs(),
                step=self.session.step,
                name=tool_call.name,
                arguments=tool_call.arguments,
            )
        )
        yield ManagedEvent("tool_started", {"name": tool_call.name, "arguments": tool_call.arguments})
        self.session.append_event("tool_started", step=self.session.step, tool_name=tool_call.name, arguments=tool_call.arguments)
        self._persist_session()

        auto_loaded_skill = self.session_engine.skill_loader.load_skill_for_tool(tool_call.name)
        if auto_loaded_skill:
            self.session_engine.rebuild_system_prompt()
            self.session.append_event("skill_auto_loaded", skill_name=auto_loaded_skill)
            self._persist_session()
            await self._publish(SkillAutoLoaded(**self._bus_kwargs(), skill_name=auto_loaded_skill))
            yield ManagedEvent("skill_auto_loaded", {"skill_name": auto_loaded_skill})

        tool_start = time.time()
        if (validation_error := self.session_engine.dispatch.validate_call(tool_call)):
            result_content = self.session_engine.dispatch.retry_prompt(tool_call, validation_error)
            result_success = False
            if trace is not None:
                trace.record_recovery_event(
                    step=self.session.step,
                    kind="malformed_arguments",
                    tool_name=tool_call.name,
                    detail=validation_error,
                )
        else:
            tool_def = self.session_engine.dispatch.get_tool_def(tool_call.name)
            if tool_def is None:
                result_content = f"Unknown tool: {tool_call.name}"
                result_success = False
                if trace is not None:
                    trace.record_recovery_event(
                        step=self.session.step,
                        kind="unknown_tool",
                        tool_name=tool_call.name,
                        detail=result_content,
                    )
            elif self.access_controller is not None:
                if tool_def.compliance_scope == "education":
                    self._mark_education_scope_used()
                    async for event in self._emit_education_disclaimer_if_needed():
                        yield event
                decision = self.access_controller.evaluate(tool_call, tool_def)
                if trace is not None:
                    trace.record_approval_decision(
                        step=self.session.step,
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
                    await self._publish(
                        ToolDenied(
                            **self._bus_kwargs(),
                            name=tool_call.name,
                            reason=decision.reason,
                        )
                    )
                    yield ManagedEvent("tool_denied", {"name": tool_call.name, "reason": decision.reason})
                elif decision.action == PermissionAction.ASK:
                    pending = self.access_controller.create_pending(tool_call, decision)
                    self.session.pending_approval = pending
                    self.session.set_state(AgentState.WAITING_APPROVAL, reason=decision.reason)
                    self.session.append_event("approval_requested", tool_name=tool_call.name, reason=decision.reason)
                    self._persist_session()
                    await self._publish(
                        ApprovalRequested(
                            **self._bus_kwargs(),
                            step=self.session.step,
                            tool_name=tool_call.name,
                            reason=decision.reason,
                        )
                    )
                    await self._emit_stream_end("waiting_approval", reason=decision.reason)
                    yield ManagedEvent(
                        "approval_requested",
                        {"tool_name": tool_call.name, "reason": decision.reason, "step": self.session.step},
                    )
                    return
                else:
                    tool_ms, result_content, result_success = await self._execute_allowed_tool_call(tool_call)
                    if tool_def.compliance_scope == "education":
                        result_content, allowed = enforce_education_content(result_content)
                        result_success = result_success and allowed
                    search_results = self._extract_search_results(tool_name=tool_call.name, content=result_content)
                    if not result_success and trace is not None:
                        trace.record_recovery_event(
                            step=self.session.step,
                            kind="tool_execution_failed",
                            tool_name=tool_call.name,
                            detail=result_content[:200],
                        )
                    self.session_engine.add_tool_message(tool_call.id, tool_call.name, result_content)
                    self.session.append_event(
                        "tool_finished",
                        tool_name=tool_call.name,
                        arguments=tool_call.arguments,
                        success=result_success,
                        duration_ms=tool_ms,
                        content=result_content,
                        search_results=search_results,
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
                    await self._publish(
                        ToolFinished(
                            **self._bus_kwargs(),
                            step=self.session.step,
                            name=tool_call.name,
                            arguments=tool_call.arguments,
                            success=result_success,
                            duration_ms=tool_ms,
                            content=result_content,
                            search_results=search_results,
                        )
                    )
                    yield ManagedEvent(
                        "tool_finished",
                        {
                            "name": tool_call.name,
                            "arguments": tool_call.arguments,
                            "success": result_success,
                            "duration_ms": tool_ms,
                            "content": result_content,
                            "search_results": search_results,
                        },
                    )
                    return
            else:
                if tool_def.compliance_scope == "education":
                    self._mark_education_scope_used()
                    async for event in self._emit_education_disclaimer_if_needed():
                        yield event
                tool_ms, result_content, result_success = await self._execute_tool_call(tool_call)
                if tool_def.compliance_scope == "education":
                    result_content, allowed = enforce_education_content(result_content)
                    result_success = result_success and allowed
                search_results = self._extract_search_results(tool_name=tool_call.name, content=result_content)
                if not result_success and trace is not None:
                    trace.record_recovery_event(
                        step=self.session.step,
                        kind="tool_execution_failed",
                        tool_name=tool_call.name,
                        detail=result_content[:200],
                    )
                self.session_engine.add_tool_message(tool_call.id, tool_call.name, result_content)
                self.session.append_event(
                    "tool_finished",
                    tool_name=tool_call.name,
                    arguments=tool_call.arguments,
                    success=result_success,
                    duration_ms=tool_ms,
                    content=result_content,
                    search_results=search_results,
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
                await self._publish(
                    ToolFinished(
                        **self._bus_kwargs(),
                        step=self.session.step,
                        name=tool_call.name,
                        arguments=tool_call.arguments,
                        success=result_success,
                        duration_ms=tool_ms,
                        content=result_content,
                        search_results=search_results,
                    )
                )
                yield ManagedEvent(
                    "tool_finished",
                    {
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                        "success": result_success,
                        "duration_ms": tool_ms,
                        "content": result_content,
                        "search_results": search_results,
                    },
                )
                return

        tool_ms = (time.time() - tool_start) * 1000
        result_content = self.session_engine.context_mgr.compact_tool_result(result_content)
        search_results = self._extract_search_results(tool_name=tool_call.name, content=result_content)
        self.session_engine.add_tool_message(tool_call.id, tool_call.name, result_content)
        self.session.append_event(
            "tool_finished",
            tool_name=tool_call.name,
            arguments=tool_call.arguments,
            success=result_success,
            duration_ms=tool_ms,
            content=result_content,
            search_results=search_results,
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
        await self._publish(
            ToolFinished(
                **self._bus_kwargs(),
                step=self.session.step,
                name=tool_call.name,
                arguments=tool_call.arguments,
                success=result_success,
                duration_ms=tool_ms,
                content=result_content,
                search_results=search_results,
            )
        )
        yield ManagedEvent(
            "tool_finished",
            {
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "success": result_success,
                "duration_ms": tool_ms,
                "content": result_content,
                "search_results": search_results,
            },
        )

    def _check_runtime_limits(self, guard: RuntimeGuard) -> str | None:
        if self._cancel_requested():
            return "Run cancelled by user"
        return guard.check()

    def _extract_search_results(
        self,
        *,
        tool_name: str,
        content: str,
    ) -> list[dict[str, Any]]:
        if tool_name != "web_research":
            return []
        try:
            payload = json.loads(content)
        except Exception:
            return []
        results = payload.get("results", [])
        if not isinstance(results, list):
            return []

        cards: list[dict[str, Any]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            cards.append({
                "title": str(item.get("title") or url).strip(),
                "url": url,
                "snippet": str(item.get("snippet") or "").strip(),
                "source": urlparse(url).netloc.replace("www.", "") or None,
                "timestamp": item.get("timestamp"),
            })
        return cards

    def _cancel_requested(self) -> bool:
        return bool(self.session.metadata.get("cancel_requested", False))

    def _set_cancel_requested(self, value: bool) -> None:
        self.session.metadata["cancel_requested"] = value

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
        ctx = ToolContext(
            session_id=self.session.session_id,
            turn_id=self.session.turn_id,
            event_bus=self.event_bus,
            artifact_store=self.artifact_store,
        )
        try:
            if not self._sandbox_provisioned:
                await self.sandbox.provision(resources=get_sandbox_resources())
                self._sandbox_provisioned = True
            with sandbox_context(self.sandbox), tool_context_scope(ctx):
                result = await self.session_engine.dispatch.execute(tool_call)
        except Exception as exc:
            tool_ms = (time.time() - tool_start) * 1000
            message = self.session_engine.context_mgr.compact_tool_result(
                f"Error executing {tool_call.name}: {exc}"
            )
            return tool_ms, message, False
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
            callback(AgentEvent(type=EventType.LLM_CALL_START, step=self.session.step, data=event.data))
        elif event.type == "education_disclaimer":
            trace.add_event(AgentEvent(
                type=EventType.COMPLIANCE_NOTICE,
                step=self.session.step,
                data=event.data,
            ))
            callback(AgentEvent(
                type=EventType.COMPLIANCE_NOTICE,
                step=self.session.step,
                data=event.data,
            ))
        elif event.type == "usage":
            usage = event.data["usage"]
            trace.add_llm_usage(usage)
            trace.add_event(AgentEvent(
                type=EventType.LLM_CALL_END,
                step=self.session.step,
                data={"tokens": usage.model_dump(), "duration_ms": round(event.data["duration_ms"], 1)},
            ))
            callback(AgentEvent(
                type=EventType.LLM_CALL_END,
                step=self.session.step,
                data={"tokens": usage.model_dump(), "duration_ms": round(event.data["duration_ms"], 1)},
            ))
        elif event.type == "tool_started":
            callback(AgentEvent(type=EventType.TOOL_CALL_START, step=self.session.step, data=event.data))
        elif event.type == "tool_finished":
            content_preview = event.data.get("content", "")[:400]
            urls = re.findall(r"https?://[^\s\"'<>]+", event.data.get("content", ""))
            trace.add_event(AgentEvent(
                type=EventType.TOOL_CALL_END,
                step=self.session.step,
                data={
                    "name": event.data["name"],
                    "success": event.data["success"],
                    "content_preview": content_preview,
                    "urls": urls[:20],
                    "duration_ms": round(event.data["duration_ms"], 1),
                },
            ))
            callback(AgentEvent(
                type=EventType.TOOL_CALL_END,
                step=self.session.step,
                data={
                    "name": event.data["name"],
                    "success": event.data["success"],
                    "content_preview": content_preview,
                    "urls": urls[:20],
                    "duration_ms": round(event.data["duration_ms"], 1),
                },
            ))
            trace.record_tool_call(
                step=self.session.step,
                name=event.data["name"],
                arguments=event.data.get("arguments", {}),
                success=event.data["success"],
                duration_ms=event.data["duration_ms"],
                result_size=len(event.data.get("content", "")),
                urls=urls[:20],
                content_preview=content_preview,
            )
        elif event.type == "turn_finished":
            final_content = event.data.get("content", "")
            trace.finish(output=final_content, stop_reason=self.session.stop_reason or "completed")
            callback(AgentEvent(
                type=EventType.AGENT_END,
                step=self.session.step,
                data={"output_preview": final_content[:200]},
            ))
        return final_content

    def _education_scope_used(self) -> bool:
        return bool(self.session.metadata.get("education_scope_used", False))

    def _mark_education_scope_used(self) -> None:
        self.session.metadata["education_scope_used"] = True

    async def _emit_education_disclaimer_if_needed(self) -> AsyncIterator[ManagedEvent]:
        if self.session.metadata.get("education_disclaimer_emitted", False):
            return
        self.session.metadata["education_disclaimer_emitted"] = True
        self.session.append_event(
            "education_disclaimer",
            message=DISCLAIMER_MESSAGE,
            scope="education",
        )
        self._persist_session()
        await self._publish(
            EducationDisclaimer(
                **self._bus_kwargs(),
                message=DISCLAIMER_MESSAGE,
                scope="education",
            )
        )
        yield ManagedEvent(
            "education_disclaimer",
            {"message": DISCLAIMER_MESSAGE, "scope": "education"},
        )

    def _persist_session(self) -> None:
        if self.archive is not None:
            # Append unpersisted events BEFORE updating state. Order matters:
            # if state flipped first, a consumer polling in the gap between the
            # state write and the event writes would see a terminal state, miss
            # the trailing events, and exit the stream prematurely.
            persisted_seq = self.archive.get_last_seq(self.session.session_id)
            for event in self.session.events[persisted_seq:]:
                try:
                    self.archive.emit_event(
                        self.session.session_id,
                        event["type"],
                        event.get("payload", {}),
                    )
                except Exception:
                    logger.debug("Archive event write failed (non-fatal)", exc_info=True)
                    break
            try:
                self.archive.update_session_state(
                    self.session.session_id,
                    self.session.state.value,
                    self.session.stop_reason,
                    metadata=self._archive_metadata_snapshot(),
                )
            except Exception:
                logger.debug("Archive state update failed (non-fatal)", exc_info=True)

    def _archive_metadata_snapshot(self) -> dict[str, Any]:
        return {
            "session_metadata": dict(self.session.metadata),
            "runtime_state": {
                "step": self.session.step,
                "current_user_input": self.session.current_user_input,
                "cancel_requested": self._cancel_requested(),
                "pending_approval": (
                    self.session.pending_approval.model_dump()
                    if self.session.pending_approval is not None
                    else None
                ),
            },
        }
