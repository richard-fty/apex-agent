# Apex Agent Design Spec

Reference: [Anthropic — Managed Agents](https://www.anthropic.com/engineering/managed-agents)

Apex Agent is a managed-agent system. It follows the article's core idea: the three things Claude actually needs — **session**, **harness**, **sandbox** — are virtualized at interface boundaries so each can fail, scale, or be replaced independently. Brain and hands are metaphors layered on top of those three primitives.

This document defines the target design. For what is shipped vs. aspirational, see §Current State. For validation, see [eval-suite.md](eval-suite.md).

## 1. Architecture

The managed-agent shape is a hub-and-spoke: a stateless **harness** at the center, with four virtualized surfaces around it. This mirrors the diagram in Anthropic's article.

```
                         ┌─────────────────┐
                         │      Tools      │
                         │ + Resources/MCP │
                         └────────┬────────┘
                                  ▲
                       execute(name, input)
                                  ▼
  ┌──────────┐    getEvents   ┌───┴────┐    provision   ┌──────────┐
  │ Session  │◄──────────────►│Harness │◄──────────────►│ Sandbox  │
  │  (log)   │    emitEvent   │ (loop) │                │  (exec)  │
  └──────────┘                └───┬────┘                └──────────┘
                                  ▲
                         wake / lifecycle
                                  ▼
                         ┌────────┴────────┐
                         │  Orchestration  │
                         │   (scheduler)   │
                         └─────────────────┘
```

| Node | Role | Interface |
|---|---|---|
| **Harness** | Stateless agent loop: assemble context, call brain, route tool calls, write events | center of the hub |
| **Session** | Append-only durable event log; source of truth outside the model context | `getEvents`, `emitEvent` |
| **Sandbox** | Isolated, disposable execution environment (no credentials inside) | `provision(resources)` |
| **Tools** | Universal hands: built-in tools, resources, MCP servers — all addressed the same way | `execute(name, input) -> str` |
| **Orchestration** | Lifecycle above the loop: schedule runs, `wake(session_id)` on recovery, enforce limits, collect metrics | works *on* sessions, not inside them |

The **brain** is Claude + the harness that feeds it. The **hands** are the sandbox and the tools the harness routes to. Frontends (TUI, CLI, eval runner) are not part of the core shape — they plug in as **consumers of the session event stream** (see §7.4).

## 2. Primary Components

### 2.1 Session

> "the append-only log of everything that happened" — Anthropic

The session is **the durable event log**. It is the source of truth, not the model context window.

Responsibilities:
- accept event appends: user input, assistant output, tool calls, tool results, approval decisions, errors
- survive harness crashes, process restarts, and multiple consumer brains
- expose a positional read interface so any consumer (harness, TUI, evaluator) can reconstruct state

Required events (minimum):
- `user_message`
- `assistant_message`
- `tool_call_started`
- `tool_call_finished`
- `approval_requested` / `approval_resolved`
- `state_changed` (`idle → running → waiting_approval → completed | failed | cancelled`)
- `context_prepared` (what was sent to the model)
- `retrieval_injection`
- `recovery_event` (malformed args, tool failure, unknown tool)

In this repo:
- `agent/session/engine.py` — turn-scoped session state
- `agent/session/store.py` — JSON-file persistence (first durable implementation)

Target: promote the store to an append-only event log with positional reads (`get_events(session_id, after=cursor)`).

### 2.2 Harness

> "the loop that calls Claude and routes Claude's tool calls to the relevant infrastructure" — Anthropic

The harness is the control loop. It must be **small, explicit, and stateless at the instance level** — any harness instance can be torn down and a new one can `wake(session_id)` to resume from the log.

Responsibilities per iteration:
1. `get_events(session_id)` — read session log
2. assemble model-ready context (system + skills + retrieval + compressed history + recent turns)
3. call the brain
4. parse tool calls
5. validate them against policy
6. route via `execute(name, input)`
7. `emit_event(session_id, event)` for every step
8. decide continue / pause (approval) / stop

In this repo:
- `agent/runtime/loop.py` — entry
- `agent/runtime/managed_runtime.py` — the loop body (currently holds some run-scoped state; target: move that state into session)
- `agent/runtime/tool_dispatch.py` — tool registry + routing
- `agent/context/assembler.py` — context assembly
- `eval/runner.py` — eval driver that wraps the harness for scenario runs

### 2.3 Sandbox

> "an execution environment where Claude can run code and edit files" — Anthropic

The sandbox is the isolated execution boundary. Risky work (shell, file writes, untrusted code) runs here and nowhere else.

Requirements:
- replaceable (local, container, remote)
- disposable — provisioned per session or per sensitive task
- **credentials never live inside the sandbox**; auth is either bundled with a provisioned resource or fetched from an external vault (MCP proxy / secret manager)

In this repo:
- `agent/runtime/sandbox.py` — `BaseSandbox` + `LocalSandbox`. LocalSandbox is a stable seam, not yet strong isolation.

Target: containerized or VM-backed sandbox with `provision({resources})` and `destroy()`, so sandboxes are per-session and disposable.

## 3. Interface Contracts

These are the stable interfaces the rest of the system should target. Where the current code uses a different shape, that's flagged in §Current State.

| Interface | Purpose |
|---|---|
| `get_session(id) -> Session` | recover a session handle |
| `get_events(id, after=cursor) -> list[Event]` | read the log |
| `emit_event(id, event) -> ack` | append to the log |
| `execute(name, input) -> str` | universal hands interface — same shape for tools, scripts, MCP servers |
| `provision(resources) -> Sandbox` | initialize a sandbox with auth/resources bundled |
| `wake(session_id) -> HarnessHandle` | boot a fresh harness on an existing session |

`execute` returning a string is deliberate: it keeps every hand interchangeable from the brain's point of view.

## 4. Runtime Flow

1. Frontend submits a task; orchestrator creates or resumes a session via `get_session`.
2. Harness boots (or `wake`s) on that session and calls `get_events`.
3. Harness transforms events into model-ready context, injects retrieval if the policy says so.
4. Brain returns text or tool calls.
5. Harness validates each tool call, consults policy, and calls `execute(name, input)`.
6. Each step is written back with `emit_event`.
7. If a tool requires approval, harness emits `approval_requested` and stops. Any future harness can resume by calling `wake(session_id)` once the approval is resolved.
8. Loop ends on completion, step/time/budget limit, cancellation, or failure — each recorded as a terminal event.

## 5. Security Model

Security comes from structure, not prompt text.

- Every action is a tool; there is no side channel between brain and hands.
- Tools carry metadata (`is_read_only`, `is_destructive`, `is_networked`, `mutates_state`) that policy reads — never special-case by tool name.
- Risky actions default to **fail-closed**: unknown tool → reject; unknown arg → retry hint; unvalidated action → ask.
- Credentials stay outside the sandbox. The sandbox can *use* a resource handle (e.g. a scoped git token bound to one clone), but cannot retrieve arbitrary secrets.
- Approval decisions are events, not UI state — they persist through harness restarts.

## 6. Hands

Hands split into two layers. Both are reachable only through `execute(name, input)`.

| Layer | Path | Exposed to brain? | Role |
|---|---|---|---|
| Tools | `tools/` | Yes, as tool calls | Built-in capabilities: filesystem, shell (via sandbox), web, rag |
| Skill Packs | `skill_packs/` (see §7) | Only when a pack is loaded | Pluggable domain packs with their own tool surface |

Runtime-internal helpers like `services/retrieval_policy.py` and `services/search_orchestrator.py` are **not hands** — they are harness-side services that decide *when* to inject context or *which* hand to call. They never appear as tool calls.

## 7. Apex Extensions

These go beyond the article. Each is a runtime-level concern implemented to match the managed-agent shape.

### 7.1 Skill Packs

Pluggable domain packs installed on disk as `SKILL.md` + `REFERENCE.md` + `tools.py`. A pack advertises keywords; the skill loader pre-loads a pack when intent matches, registers its tools into the dispatcher, and injects its structured prompt.

- `skill_packs/` — installed packs (content)
- `agent/skills/` — runtime analyzer + loader

### 7.2 Retrieval Policy

Retrieval is a **harness service**, not a tool the brain calls. `services/retrieval_policy.py` inspects user input and decides whether to gather local-first evidence (via [rag-service](https://github.com/richard-fty/rag-service)), fall back to web, or skip retrieval. Injected context is attributable (source + score) and compacted before merge.

### 7.3 Approval Model

Every tool call resolves to `allow | ask | deny` through policy metadata, not tool names. `ask` moves the session to `waiting_approval` and persists pending state; any harness can resume the run. Permission modes: `plan`, `default`, `accept_edits`, `auto`, `dont_ask`.

### 7.4 TUI

The TUI is a **frontend over the session event stream**, not a second runtime. It:
- subscribes to harness events (via the same stream the trace consumes)
- renders token-level output, tool calls, retrieval stages, approval prompts
- sends user messages and approval resolutions back to the harness
- does not own any state the session doesn't also have

Path: `tui/`. Rule: if removing the TUI breaks any behavior outside `tui/`, that's a bug.

### 7.5 Eval Suite

Treated as part of the product. Scenarios live in `scenarios/`, run by `eval/runner.py`, graded per scenario. The suite covers task success, tool selection, recovery, context/memory, approval/safety, orchestration/lifecycle, and efficiency. Details: [eval-suite.md](eval-suite.md). Design review checklist: [design-checklist.md](design-checklist.md).

Release gate: no regression on safety or lifecycle cases; task success stable or better; cost within budget.

## 8. Current State

| Concept | Status | Where |
|---|---|---|
| Session as durable log | **partial** — JSON record with events, rewritten on each step | `agent/session/store.py` |
| Stateless harness + `wake` | **not shipped** — harness holds run-scoped state on the instance | `agent/runtime/managed_runtime.py` |
| Sandbox boundary | **seam in place** — LocalSandbox; not yet isolated | `agent/runtime/sandbox.py` |
| Brain adapter | **shipped** — LiteLLMBrain | `agent/runtime/managed_runtime.py` |
| Tool dispatch + metadata | **shipped** | `agent/runtime/tool_dispatch.py`, `agent/core/models.py` |
| Retrieval as service | **shipped** | `services/retrieval_policy.py` |
| Approval model | **shipped** — allow/ask/deny with resumable pending | `agent/policy/access_control.py`, `agent/policy/approval_manager.py` |
| Skill packs | **shipped** — discover + analyze + load | `skill_packs/`, `agent/skills/` |
| TUI as event consumer | **shipped** | `tui/` |
| Eval suite scenarios | **partial** — `core_agent` + `stock_strategy` scaffolded | `scenarios/` |

## 9. Roadmap

In priority order:

1. Promote `SessionStore` to an append-only event log with positional reads; stop rewriting the whole record per event.
2. Move harness run-scoped state (`_step`, `_guard`, `_current_user_input`) into the session log so any harness instance can `wake(session_id)` cleanly.
3. Land the 12 baseline eval cases from [eval-suite.md](eval-suite.md) under `scenarios/core_agent/`.
4. Add failure-injection in the harness (malformed args, tool errors, context overflow) and recovery scoring.
5. Ship a containerized sandbox implementation with `provision({resources})` and credential isolation.
6. Add `execute(name, input) -> str` as the single hands interface; collapse per-layer special cases.
7. Collapse `agent/runtime/{loop,managed_runtime,orchestrator,shared_runner}.py` into a single small harness loop (four files currently overlap — the article has one stateless harness).

## 10. What Good Looks Like

- Session is the only source of truth; harnesses are disposable.
- Sandboxes are per-session and hold no credentials.
- Every action the agent can take is a tool with metadata; policy reads metadata, not names.
- The TUI, CLI, and benchmark harness all consume the same event stream and can't diverge from session truth.
- The eval suite gates every runtime change.
