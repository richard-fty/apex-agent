"""Core agent loop — model-agnostic, harness-hooked, production-grade.

Lifecycle of a user message:
  1. PRE-PROCESSING
     - Register built-in tools (filesystem, shell, web)
     - Discover available skills
     - Register skill meta-tools (list_skills, load_skill, etc.)
     - Build system prompt with skill index (Level 1)

  2. AGENT LOOP
     a. Context management — fit messages within token budget
     b. Send to LLM via LiteLLM (messages + active tool schemas)
     c. Parse response:
        - Text only → done
        - Tool calls → validate → execute → append results
        - Malformed call → return error with retry hint
     d. If skill loaded/unloaded → rebuild system prompt in messages
     e. Check runtime limits (steps, timeout)
     f. Loop

  3. POST-PROCESSING
     - Finalize trace with metrics
     - Return trace
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable

import litellm

from agent.context.manager import ContextManager
from agent.models import AgentEvent, EventType, TokenUsage
from agent.prompts import build_system_prompt
from agent.skill_loader import SkillLoader
from agent.tool_dispatch import ToolDispatch
from harness.runtime import RuntimeConfig, RuntimeGuard
from harness.token_tracker import extract_usage
from harness.trace import Trace
from tools.base import get_all_builtin_tools
from tools.skill_meta import SkillMetaTools


EventCallback = Callable[[AgentEvent], None]

# Skills that modify the tool registry — system prompt must be rebuilt after these
_SKILL_MUTATING_TOOLS = {"load_skill", "unload_skill"}


def _noop_callback(event: AgentEvent) -> None:
    pass


async def run_agent(
    user_input: str,
    model: str,
    context_strategy: str = "truncate",
    runtime_config: RuntimeConfig | None = None,
    event_callback: EventCallback | None = None,
) -> Trace:
    """Run the agent loop for a single user request."""
    callback = event_callback or _noop_callback
    config = runtime_config or RuntimeConfig()
    guard = RuntimeGuard(config)
    run_id = str(uuid.uuid4())[:8]

    # Initialize trace
    trace = Trace(
        run_id=run_id,
        model=model,
        scenario="general",
        prompt=user_input,
        context_strategy=context_strategy,
    )

    # ── 1. PRE-PROCESSING ──────────────────────────────────────────────

    # Set up tool dispatch
    dispatch = ToolDispatch()

    # Register built-in tools (filesystem, shell, web)
    for tool in get_all_builtin_tools():
        dispatch.register(tool.to_tool_def(), tool.execute)

    # Discover available skills
    skill_loader = SkillLoader(dispatch)
    skill_loader.discover()

    # Register skill meta-tools (load_skill, unload_skill, list_skills, read_skill_reference)
    meta_tools = SkillMetaTools(skill_loader)
    for tool_def, handler in meta_tools.get_tool_pairs():
        dispatch.register(tool_def, handler)

    # Build initial system prompt (base + skill index)
    system_prompt = build_system_prompt(skill_loader)

    # Context manager
    context_mgr = ContextManager(strategy_name=context_strategy, model=model)

    # Initial messages
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]

    # Emit start event
    callback(AgentEvent(
        type=EventType.AGENT_START,
        data={
            "run_id": run_id,
            "model": model,
            "available_skills": skill_loader.get_available_skill_names(),
            "available_tools": dispatch.tool_names,
        },
    ))

    # ── 2. AGENT LOOP ──────────────────────────────────────────────────

    step = 0
    assistant_content = ""

    try:
        while True:
            # Check runtime limits
            limit_error = guard.check()
            if limit_error:
                trace.finish(error=limit_error)
                callback(AgentEvent(type=EventType.AGENT_ERROR, step=step, data={"error": limit_error}))
                break

            # Context management — fit within budget
            tools_schema = dispatch.to_openai_tools()
            fitted_messages = await context_mgr.prepare(messages, tools_schema)

            # Emit LLM call start
            callback(AgentEvent(
                type=EventType.LLM_CALL_START,
                step=step,
                data={
                    "message_count": len(fitted_messages),
                    "tool_count": len(tools_schema),
                    "loaded_skills": skill_loader.get_loaded_skill_names(),
                },
            ))

            llm_start = time.time()

            # Call LLM via LiteLLM
            response = await litellm.acompletion(
                model=model,
                messages=fitted_messages,
                tools=tools_schema if tools_schema else None,
            )

            llm_duration_ms = (time.time() - llm_start) * 1000

            # Extract token usage
            usage = extract_usage(response)
            trace.add_llm_usage(usage)

            # Parse response
            choice = response.choices[0]
            assistant_msg = choice.message

            # Emit LLM response
            callback(AgentEvent(
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
                data={
                    "tokens": usage.model_dump(),
                    "duration_ms": round(llm_duration_ms, 1),
                },
            ))

            # ── Handle tool calls ──────────────────────────────────────

            if assistant_msg.tool_calls:
                # Build assistant message with tool calls for history
                assistant_dict: dict[str, Any] = {"role": "assistant"}
                if assistant_msg.content:
                    assistant_dict["content"] = assistant_msg.content
                assistant_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in assistant_msg.tool_calls
                ]
                messages.append(assistant_dict)

                # Parse tool calls
                raw_calls = [
                    {
                        "id": tc.id,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in assistant_msg.tool_calls
                ]
                parsed_calls = dispatch.parse_tool_calls(raw_calls)

                skill_changed = False

                for tool_call in parsed_calls:
                    callback(AgentEvent(
                        type=EventType.TOOL_CALL_START,
                        step=step,
                        data={"name": tool_call.name, "arguments": tool_call.arguments},
                    ))

                    tool_start = time.time()

                    # Validate before executing
                    validation_error = dispatch.validate_call(tool_call)
                    if validation_error:
                        # Return error with retry hint
                        retry_hint = dispatch.retry_prompt(tool_call, validation_error)
                        result_content = retry_hint
                        result_success = False
                    else:
                        # Execute the tool
                        result = await dispatch.execute(tool_call)
                        result_content = result.content
                        result_success = result.success

                    tool_duration_ms = (time.time() - tool_start) * 1000

                    # Compact large tool results to save context
                    result_content = context_mgr.compact_tool_result(result_content)

                    callback(AgentEvent(
                        type=EventType.TOOL_CALL_END,
                        step=step,
                        data={
                            "name": tool_call.name,
                            "success": result_success,
                            "content_preview": result_content[:200],
                            "duration_ms": round(tool_duration_ms, 1),
                        },
                    ))
                    trace.add_event(AgentEvent(
                        type=EventType.TOOL_CALL_END,
                        step=step,
                        data={
                            "name": tool_call.name,
                            "success": result_success,
                            "duration_ms": round(tool_duration_ms, 1),
                        },
                    ))

                    # Append tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": result_content,
                    })

                    # Track if skills were modified
                    if tool_call.name in _SKILL_MUTATING_TOOLS:
                        skill_changed = True

                # If skills were loaded/unloaded, rebuild the system prompt
                if skill_changed:
                    new_system_prompt = build_system_prompt(skill_loader)
                    messages[0] = {"role": "system", "content": new_system_prompt}

                guard.increment_step()
                step += 1

            else:
                # ── No tool calls — agent is done ──────────────────────
                if assistant_msg.content:
                    assistant_content = assistant_msg.content
                    messages.append({"role": "assistant", "content": assistant_content})

                trace.finish(output=assistant_content)
                callback(AgentEvent(
                    type=EventType.AGENT_END,
                    step=step,
                    data={
                        "output_preview": (assistant_content or "")[:200],
                        "loaded_skills": skill_loader.get_loaded_skill_names(),
                    },
                ))
                break

    except Exception as e:
        trace.finish(error=str(e))
        callback(AgentEvent(
            type=EventType.AGENT_ERROR,
            step=step,
            data={"error": str(e)},
        ))

    # ── 3. POST-PROCESSING ─────────────────────────────────────────────

    return trace
