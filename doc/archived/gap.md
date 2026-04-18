# Apex Agent Gap

This document lists the main implementation gaps between the current codebase and the target design in [design-spec.md](design-spec.md) and [eval-suite.md](eval-suite.md).

## Scope

This is not a rewrite of the design spec.
It is a delta document:

- what the spec says
- what the repo currently does
- what is still missing

## High-Level Status

The project already matches the design direction in several important ways:

- tool metadata exists and is used by runtime policy
- retrieval is implemented as a runtime service, not a user-facing tool workflow
- approvals can pause a run and be resumed
- dynamic tool visibility exists
- skill pre-load, plan state, and context assembly are implemented
- a scenario-based eval harness exists

The main gaps are structural:

- the default session persistence path is not append-only
- the default harness is not yet stateless
- restart recovery is partial rather than complete
- the sandbox is only a seam, not an isolated disposable environment
- the TUI consumes live runner events rather than reconstructing from session truth
- the eval suite in code is much smaller than the eval suite described in the docs

## Gap List

### 1. Session Log Is Not Append-Only By Default

Design target:

- session is the durable source of truth
- events are append-only
- consumers can read by cursor with `get_events(session_id, after=cursor)`

Current implementation:

- `agent/session/store.py` rewrites a full JSON record on each update
- the session record stores `events` as one in-memory list that gets rewritten to disk

Why this is a gap:

- it does not satisfy the primary session contract in the design
- it does not satisfy T1.1 `session_log_is_append_only` in the eval suite
- rewriting the full record makes crash recovery and concurrent readers weaker

What exists already:

- `agent/session/archive.py` implements an append-only SQLite event log with sequence numbers and positional reads

What is missing:

- make `SessionArchive` the default persistence path for the runtime
- stop treating the JSON store as the primary session source of truth
- move replay and state reconstruction onto the append-only archive path

### 2. Harness Is Still Stateful

Design target:

- harness instances are disposable
- any fresh harness can `wake(session_id)` and continue from session truth alone
- run-scoped state should live in the session log, not on the runtime instance

Current implementation:

- `agent/runtime/managed_runtime.py` stores `_current_user_input`, `_guard`, `_step`, and `_active_trace` on the runtime instance
- `run_to_completion()` depends on instance-local runtime state

Why this is a gap:

- this does not satisfy the stateless harness requirement in the design spec
- it weakens `wake(session_id)` because important execution state is reconstructed indirectly

What is missing:

- move step count, pending execution state, approval wait state, and current turn identity into persisted session state
- make the runtime loop reconstruct itself only from session data plus config

### 3. `wake()` Exists, But Recovery Is Partial

Design target:

- restart recovery should restore messages, loaded skills, approvals, plan state, and progress without repeating completed work

Current implementation:

- `agent/runtime/wake.py` rebuilds messages, skill loads, plan state, and pinned facts from the archive
- it derives step count from prior `tool_finished` events

Why this is still a gap:

- pending approval is detected but not fully rehydrated into an actionable approval object
- the resumed runtime still depends on instance-local machinery after reconstruction
- there is no strong guarantee that resumed execution will avoid repeating already completed work under all failure points

What is missing:

- persist enough structured state to rebuild pending approval exactly
- restore access-controller pending state directly from session events
- add integration tests for crash-mid-tool and post-approval restart flows

### 4. Sandbox Is Not Isolated Or Disposable

Design target:

- sandbox should be replaceable, disposable, and per-session or per-sensitive-task
- credentials must stay outside the sandbox
- sandbox should expose provisioning and teardown semantics

Current implementation:

- `agent/runtime/sandbox.py` provides `BaseSandbox` and `LocalSandbox`
- `LocalSandbox` executes shell commands on the host and reads/writes host files directly

Why this is a gap:

- there is no credential isolation
- there is no per-session sandbox lifecycle
- there is no `provision(resources)` / `destroy()` contract
- this does not satisfy T1.5 `sandbox_credential_isolation` or T1.6 `sandbox_disposable_per_session`

What is missing:

- container or VM backed sandbox implementation
- explicit sandbox provisioning API
- per-session filesystem and environment isolation
- tests that verify secret isolation and session disposal

### 5. TUI Is Not Yet A Pure Session-Stream Consumer

Design target:

- TUI should be a frontend over the session event stream
- removing the TUI should not affect runtime behavior
- UI state should not be more authoritative than session state

Current implementation:

- `tui/app.py` consumes live runner events from `SharedTurnRunner`
- the UI updates directly from runtime emissions instead of replaying persisted session events

Why this is a gap:

- the TUI is coupled to the active runtime stream rather than the session log as source of truth
- this falls short of the design rule that all consumers should observe the same persisted event stream

What is missing:

- a session-event subscription or replay interface used by TUI, CLI, and eval
- separation between transient UI presentation and persisted runtime events

### 6. Trace Richness Does Not Yet Match The Eval Contract

Design target:

- traces should expose outcome, stop reason, step count, tool call details, approval decisions, retrieval usage, recovery events, token usage, cost, and duration

Current implementation:

- `agent/runtime/trace.py` stores aggregate usage, approval decisions, retrieval injections, and recovery events
- `agent/runtime/managed_runtime.py` maps only a subset of runtime events into trace steps

Why this is a gap:

- there is no single rich `tool_calls[]` structure with full args, success, duration, and result sizing
- explicit `run_outcome` is not recorded as its own structured field
- many session events exist only in persisted session records, not in the trace model used by evals

What is missing:

- unify trace and session event semantics
- record a normalized tool-call ledger
- make trace completeness match the trace requirements in `doc/eval-suite.md`

### 7. Eval Suite In Code Is Smaller Than The Eval Suite In Docs

Design target:

- T1 managed-agent property tests are hard release gates
- T2 covers broad core-agent ability tiers
- T3 covers Apex-specific regressions

Current implementation:

- `scenarios/core_agent/test_cases.json` contains the 12 baseline core cases
- there are scenario evaluators for `core_agent`, `research_and_report`, and `stock_strategy`
- the benchmark runner executes scenario cases and reports scores

Why this is a gap:

- the documented T1 suite is not implemented as the hard-gated system-level property tests described in `doc/eval-suite.md`
- there is no code-level implementation of the full T2 matrix
- T3 regression tracking against prior release baselines is not present

What is missing:

- explicit T1 integration tests for append-only logging, replay, crash recovery, parallel readers, sandbox isolation, approval persistence, and external orchestration limits
- broader T2 ability coverage across easy/medium/hard tiers
- baseline comparison and regression gating for T3

### 8. Orchestration Is Not Fully Externalized

Design target:

- orchestration should sit above the harness
- limits should be externally enforced
- the harness loop should remain small and focused

Current implementation:

- `RuntimeGuard` is instantiated inside the runtime
- the runtime directly checks limits during the loop
- orchestration helpers exist, but enforcement still lives largely inside the runtime

Why this is a gap:

- this falls short of T1.9 `orchestration_enforces_limits_externally`
- the harness and orchestration concerns are still mixed

What is missing:

- move limit ownership to a stronger orchestration layer
- make runtime limit decisions visible as orchestration-driven state transitions

### 9. Runtime Surface Is Still Split Across Overlapping Modules

Design target:

- a small, explicit harness loop

Current implementation:

- responsibilities are split across `loop.py`, `managed_runtime.py`, `orchestrator.py`, `shared_runner.py`, and `wake.py`

Why this is a gap:

- the runtime shape is harder to reason about than the target design
- lifecycle logic is spread across multiple entrypoints

What is missing:

- collapse overlapping runtime responsibilities into one clearer harness path
- keep orchestration, session persistence, and UI adapters thin and separate

### 10. Some Benchmarking Is Not Fully Stable

Design target:

- evals should be deterministic and repeatable wherever possible

Current implementation:

- retrieval benchmark tests use hash-based embeddings in `tests/test_rag_quality_benchmark.py` and `tests/test_squad_batch_benchmark.py`
- those embeddings rely on Python's built-in `hash()`

Why this is a gap:

- Python hash randomization can change rankings across processes
- this makes some retrieval benchmark outcomes unstable

What is missing:

- replace `hash()` with a stable hash function for deterministic benchmark embeddings
- separate deterministic CI benchmarks from optional external-data quality benchmarks

## Gaps Against The Design Checklist

The current codebase is strongest on:

- runtime-first retrieval injection
- explicit tool metadata
- dynamic tool visibility
- approval policy structure
- layered context assembly

The current codebase is weakest on:

- two-layer execution with session as the only source of truth
- fail-safe recovery after restart
- session durability model
- strong sandboxing
- eval completeness as a release gate

## Practical Priority Order

Suggested implementation order:

1. make the append-only archive the primary session store
2. move run-scoped harness state into persisted session state
3. complete `wake()` so approval and in-flight recovery are first-class
4. upgrade trace richness to match the documented eval contract
5. add the missing T1 managed-agent property tests
6. refactor the runtime into a smaller, more clearly separated harness/orchestration shape
7. ship a real disposable sandbox
8. stabilize retrieval benchmarks for repeatable CI

## Bottom Line

The repo already reflects the managed-agent design direction, but it does not yet fully satisfy the design spec as an implemented system.

The biggest missing pieces are not prompt behavior or tool availability.
They are:

- durable session truth
- disposable stateless harness recovery
- real sandbox isolation
- full eval-gated architecture verification
