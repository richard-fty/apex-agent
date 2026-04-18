# Apex Agent Gap Refresh

This document is a refreshed delta after the latest round of gap filling.
It should be reviewed alongside [gap.md](gap.md), but it is intended to be
the more accurate snapshot of what is still missing right now.

## What Changed Since `gap.md`

The previous gap document is now stale in a few important places.

These items are largely filled:

- trace richness is much closer to the documented eval contract
- T1 managed-agent property tests now exist in code
- retrieval benchmark hashing is now deterministic
- `wake()` and approval rehydration are stronger than before
- orchestration is more externalized than before

These items are not fully filled yet:

- append-only archive is still not the only default session truth
- runtime state is still partly instance-local
- TUI still consumes live runtime events instead of session-truth replay
- sandbox isolation exists as an implementation, but is not the default path
- eval breadth and regression gating are still smaller than the docs describe

## Current Gap Status

### 1. Session Truth Is Still Split Between JSON Store And Archive

Status: open

What exists:

- `SessionArchive` provides append-only event persistence and replay
- default runtime entrypoints now wire the archive in common paths

What is still missing:

- make the archive the single primary durable session source of truth
- stop rewriting session JSON as the authoritative run record
- move session resume and replay code to depend on archive-first semantics

Why this still matters:

- session durability is still weaker than the target design
- JSON rewrite persistence remains the effective fallback truth path

### 2. Harness State Is Still Not Fully Persisted

Status: open

What exists:

- `SessionRecord` now carries `step` and `current_user_input`
- `wake()` rebuilds more state than before

What is still missing:

- persist enough structured state so a fresh harness can continue with no
  dependence on instance-local `_guard` and `_active_trace`
- make turn identity and pending execution state explicit in durable session data
- remove the assumption that direct runtime method calls can recreate missing state

Why this still matters:

- the runtime still owns important state in memory
- this prevents a fully stateless harness contract

### 3. Recovery Is Better, But Not Yet Complete

Status: partial

What exists:

- `wake()` rebuilds messages, skill loads, plan state, pinned facts, step count,
  current user input, and pending approval metadata from the archive
- pending approval can be rehydrated into a real approval object when an access
  controller is supplied

What is still missing:

- integration tests for crash-mid-tool and crash-after-approval-edge cases
- stronger guarantees that resumed execution never repeats already completed work
- removal of remaining dependence on runtime-local state after recovery

Why this still matters:

- the recovery path is materially better, but not yet strong enough to claim
  complete restart safety

### 4. Sandbox Isolation Exists, But Is Not The Default Runtime Path

Status: partial

What exists:

- `BaseSandbox` exposes `provision()` and `destroy()`
- `DockerSandbox` provides per-session container lifecycle and avoids forwarding
  host environment variables

What is still missing:

- make isolated sandboxing part of the default execution path for sensitive work
- explicitly route shell and filesystem tools through provisioned per-session sandboxes
- add stronger end-to-end tests that verify secret isolation and cleanup behavior

Why this still matters:

- the default sandbox is still `LocalSandbox`
- the architecture has the seam, but not yet default operational isolation

### 5. TUI Is Still Coupled To The Live Runner

Status: open

What exists:

- `SessionEventStream` now exists for archive-backed session replay/subscription

What is still missing:

- switch the TUI from `SharedTurnRunner` event consumption to session-stream consumption
- make UI state reconstruct solely from persisted session events
- keep live execution and UI rendering cleanly separated

Why this still matters:

- the TUI remains more tightly coupled to active execution than the design intends

### 6. Trace Contract Gap Is Largely Closed

Status: largely filled

What exists:

- trace now records `run_outcome`
- trace includes normalized `tool_calls[]`
- trace includes approval decisions, retrieval injections, recovery events,
  total usage, cost, and duration

What may still be worth tightening:

- align trace naming and session-event naming more explicitly
- ensure eval consumers rely on one canonical shape everywhere

### 7. Eval Gating Exists, But Breadth Is Still Limited

Status: partial

What exists:

- T1 managed-agent property tests are now implemented in code
- scenario evaluators exist for `core_agent`, `research_and_report`, and
  `stock_strategy`

What is still missing:

- broader T2 ability coverage across more tasks and difficulty tiers
- T3-style baseline comparison and regression gating across releases
- a stronger release gate that connects documented architecture claims to CI policy

Why this still matters:

- the system now has structural tests, but not yet the full breadth promised in docs

### 8. Orchestration Is More Externalized, But Not Absolute

Status: partial

What exists:

- `SessionOrchestrator` now owns common guard creation
- main runtime entrypoints route through the orchestrator

What is still missing:

- remove direct-runtime fallback patterns that recreate guard ownership internally
- make orchestration-owned state transitions the only supported path

Why this still matters:

- the architectural direction is correct, but the boundary is not yet strict

### 9. Runtime Surface Is Cleaner, But Still Spread Across Several Modules

Status: partial

What exists:

- `loop.py` now funnels creation through `SessionOrchestrator`
- runtime responsibilities are more coherent than before

What is still missing:

- further collapse overlapping lifecycle responsibilities across
  `managed_runtime.py`, `orchestrator.py`, `shared_runner.py`, and `wake.py`
- reduce the number of equally important entrypoints

Why this still matters:

- the runtime is easier to follow than before, but still not as small and explicit
  as the target design

### 10. Retrieval Benchmark Stability Gap Is Closed

Status: filled

What exists:

- benchmark hashing now uses stable SHA-256-based hashing instead of Python `hash()`

No immediate follow-up is required here beyond normal maintenance.

## Recommended Next Priority

Suggested next implementation order:

1. make `SessionArchive` the only primary durable session truth
2. persist the remaining run-scoped harness state needed for a stateless runtime
3. move TUI consumption onto archive-backed session streaming
4. make isolated sandbox execution the default path for sensitive tools
5. expand eval breadth and add release-to-release regression gating
6. keep simplifying the runtime/orchestration module surface

## Bottom Line

The repo has progressed meaningfully past what [gap.md](gap.md) describes.

The biggest remaining architectural gaps are now:

- single-source durable session truth
- truly stateless harness recovery
- session-truth-driven UI consumption
- default isolated execution
- broader eval and regression gating
