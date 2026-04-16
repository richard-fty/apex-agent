# Apex Agent Design Spec

This document defines the target design for `apex-agent`, using Anthropic's managed-agents article as the primary architectural reference.

Reference:
- https://www.anthropic.com/engineering/managed-agents

## Purpose

Build a managed agent system that separates:

- `brain`: the model that reasons and chooses actions
- `harness`: the loop that calls the model and routes tool calls
- `hands`: the infrastructure that performs actions
- `session`: durable state outside the model context window
- `orchestration`: the runtime layer that schedules, resumes, and recovers work

The core idea is to decouple the brain from the hands. The model should not directly own file systems, shells, credentials, or long-lived state.

## Design Principles

## 1. Decouple Brain From Hands

The LLM should decide what to do next, but not directly execute privileged actions.

Implications:
- tool execution happens through explicit runtime interfaces
- shell, filesystem, web, and retrieval are exposed as tool surfaces
- sandboxes and external services stay replaceable

In this repo:
- `agent/runtime/managed_runtime.py` is the harness-side loop
- `agent/runtime/tool_dispatch.py` and `agent/runtime/managed_runtime.py` form the handoff to tools
- `tools/` contains the hands

## 2. Keep State Outside The Brain

The model context window is not the source of truth. Durable state should live outside the LLM call and be reconstructable after failure.

Implications:
- append events instead of relying on raw transcript growth
- support checkpoints and summaries
- make recovery independent from one live process

In this repo today:
- `agent/session/engine.py` owns session state for a run
- `agent/context/` manages fitting and compression

Target direction:
- move toward a durable session/event model instead of purely in-memory run state

## 3. Harness Is The Agent Loop

The harness is the control loop that:

1. assembles context
2. calls the model
3. parses tool calls
4. validates and routes tool calls
5. records results
6. repeats until done or stopped

The harness should stay small, explicit, and inspectable.

In this repo:
- `agent/runtime/loop.py` starts the run
- `agent/runtime/managed_runtime.py` runs the per-turn loop
- `agent/context/assembler.py` assembles model-ready context

## 4. Orchestration Is Broader Than The Harness

The Anthropic article distinguishes the local loop from the system that runs the loop reliably.

For this project, orchestration means:
- session scheduling
- run lifecycle
- retries and backoff
- failure recovery
- sandbox provisioning
- approval pause/resume
- concurrency control
- cost and usage accounting

The harness is one part of orchestration, not the whole thing.

In this repo:
- `harness/runtime.py` provides basic runtime guardrails
- `harness/access_control.py` and `harness/approval_manager.py` provide approval state

Target direction:
- promote orchestration into a first-class runtime subsystem instead of scattering it across the loop and UI

## 5. Tools Are Stable Capability Boundaries

Every action the agent can take should be represented as a tool or runtime service with explicit metadata and validation.

Good tool boundaries:
- read vs write
- local vs networked
- low-risk vs high-risk
- idempotent vs side-effecting

In this repo:
- `agent/runtime/tool_dispatch.py` is the registry, schema, and execution router
- `agent/core/models.py` defines tool metadata structures
- `harness/permission_policy.py` and `harness/policy_models.py` control access policy

## 6. Security Comes From Structure

Do not rely on prompt instructions alone for safety.

The runtime must:
- validate tool calls
- classify risky actions
- require approval where needed
- keep secrets out of model context and untrusted execution
- audit external side effects

In this repo:
- access control already exists, but the long-term target should be fail-closed behavior for risky actions

## 7. Retrieval And Memory Are Runtime Capabilities

Retrieval should be injected intentionally by runtime policy, not dumped blindly into prompt history.

In this repo:
- `services/retrieval_policy.py` decides retrieval behavior
- `agent/context/assembler.py` injects retrieval context
- `tools/rag.py` exposes retrieval capabilities

Target direction:
- separate transient retrieval context from durable memory
- keep injected context compact and attributable

## 8. Evaluation Must Drive Design

The article's architecture implies that a good agent is not just smart. It must also be reliable, resumable, and secure.

This means the design must be testable at the system level:
- task success
- tool correctness
- recovery behavior
- context robustness
- approval and safety behavior
- efficiency and cost

## System Components

## Brain

Responsibilities:
- reason over current context
- decide whether to answer or call tools
- choose the next action

Current implementation:
- model call in `agent/runtime/managed_runtime.py` via LiteLLM

Requirements:
- swappable model backend
- structured tool-call output
- token and cost tracking

## Harness

Responsibilities:
- build prompt/context
- invoke model
- parse tool calls
- validate and execute tools
- append outputs back into the session
- stop on completion, timeout, or limit

Current implementation:
- `agent/runtime/loop.py`
- `agent/runtime/managed_runtime.py`
- `agent/runtime/tool_dispatch.py`

Requirements:
- explicit continue/stop conditions
- deterministic runtime limits
- observable step-by-step events

## Hands

Responsibilities:
- perform the real work

Examples:
- filesystem access
- shell execution
- web search
- retrieval
- skill-specific actions

Current implementation:
- `tools/`
- `skills/*/tools.py`

Requirements:
- typed schemas
- runtime validation
- policy metadata
- compact results suitable for context injection

## Session

Responsibilities:
- hold the run state outside one model call
- support replay and resume
- preserve context through summarization/checkpointing

Current implementation:
- `agent/session/engine.py` maintains run state in memory

Target design:
- durable event log with optional checkpoints

Minimum session record:
- user inputs
- assistant outputs
- tool calls
- tool results
- approval state
- errors
- summaries/checkpoints
- completion outcome

## Orchestration

Responsibilities:
- create and wake runs
- resume after failure
- manage approvals and pauses
- provision execution environments
- enforce retry and timeout policy
- collect metrics and traces

Current implementation:
- partial, spread across `harness/` and `agent/`

Target design:
- a dedicated orchestration layer above the harness

## Sandbox

This repo currently exposes tools directly, but the Anthropic article suggests a cleaner long-term model:

- risky execution should happen in isolated environments
- sandboxes should be replaceable and disposable
- credentials should not be placed inside the sandbox

This is a recommended future boundary for shell-like or code-execution tools.

## Target Runtime Flow

1. User submits task.
2. Orchestrator creates or resumes session.
3. Harness loads session state and builds model context.
4. Brain returns text or tool calls.
5. Harness validates and routes tool calls to hands.
6. Results are written back into session state.
7. Orchestrator decides whether to continue, pause, retry, or stop.
8. Final answer and trace are persisted.

## Interface Guidelines

Recommended stable interfaces:

- `create_session(task, metadata) -> session_id`
- `load_session(session_id) -> session`
- `append_event(session_id, event) -> ok`
- `prepare_context(session_id) -> messages, tools`
- `invoke_model(messages, tools, settings) -> response`
- `validate_tool_call(tool_call, policy) -> decision`
- `execute_tool(tool_call, runtime_context) -> result`
- `checkpoint_session(session_id, summary) -> checkpoint_id`
- `resume_session(session_id) -> run_id`
- `complete_session(session_id, outcome) -> ok`

The design should aim for these interfaces even if the first implementation stays simpler.

## Functional Requirements

The system should:

- complete multi-step tool-using tasks
- respect runtime limits
- support dynamic tool visibility
- compress context safely
- record trace and usage data
- pause for approvals where required
- recover from common transient failures

## Non-Functional Requirements

The system should be:

- observable
- resumable
- testable
- policy-driven
- model-agnostic
- cost-aware

## Near-Term Changes For This Repo

The next design improvements should be:

1. Introduce a durable session/event model behind `SessionEngine`.
2. Separate session-level orchestration from turn-level execution more cleanly.
3. Add explicit run states: `running`, `waiting_approval`, `failed`, `completed`, `cancelled`.
4. Make approval pause/resume part of the core runtime contract.
5. Expand tool metadata so policy decisions do not depend on tool-name special cases.
6. Add failure injection and recovery tests in the harness.
7. Add benchmark scenarios beyond `stock_strategy` for general agent behavior.

## What Good Looks Like

A strong version of `apex-agent` should have:

- a small, legible harness loop
- explicit tool capability boundaries
- durable session state
- approval-aware orchestration
- retrieval as a runtime service
- measurable system evals

That is the design target this repo should move toward.
