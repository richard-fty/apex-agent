# Apex Agent Gap Refresh v2

This document supersedes the earlier [gap-refresh.md](gap-refresh.md) as a
comparison against the **current codebase** and the claims in
[design-spec.md](design-spec.md) and [eval-suite.md](eval-suite.md).

The short version:

- the original archive / TUI / sandbox / stateless-runtime gaps are much smaller
  than before, and several are effectively closed in implementation
- the main remaining gaps are now **spec-alignment gaps**:
  documentation drift, eval-semantic drift, incomplete universal-hands
  unification, and incomplete release-gate enforcement

## What Is Now Effectively Filled

### 1. Archive-First Session Truth

Status: largely filled

What the code now does:

- `SessionArchive` is the durable append-only event log with positional reads
  and session-state rows
- runtime persistence writes to the archive, not JSON session files
- resume / replay paths reconstruct from archive state and events
- TUI consumption is archive-backed through `SessionEventStream`

Why this matters:

- this was one of the largest gaps in the previous refresh and is no longer the
  main problem

Residual note:

- `SessionStore` still exists in the codebase and some constructors/tests still
  accept or pass it, so there is still legacy surface area to clean up

### 2. Harness Instance State

Status: largely filled

What the code now does:

- run-scoped execution no longer depends on runtime instance fields like
  `_guard` or `_active_trace`
- guard / trace are threaded explicitly through the loop
- cancellation intent, step, current input, and pending approval are persisted
  in session metadata

Why this matters:

- this closes the earlier “runtime still owns important state in memory” issue
  in the implementation itself

### 3. TUI As Session-Truth Consumer

Status: largely filled

What the code now does:

- the TUI starts background execution separately
- the UI reads `SessionEventStream` directly from the archive cursor for the
  turn / resume operation

Why this matters:

- the TUI is now much closer to the design-spec model of a frontend over the
  session event stream rather than a second runtime

### 4. Trace Richness

Status: filled

What the code now does:

- traces record run outcome, stop reason, tool calls, approvals, retrieval
  injections, recovery events, token usage, duration, and cost

Why this matters:

- this is now aligned with the trace contract the eval suite wants

## Remaining Gaps

### 1. Design Spec Drift

Status: open

What is wrong:

- `design-spec.md` still describes several things as aspirational that are now
  implemented or mostly implemented
- the “Current State” table is stale in important ways
- the roadmap still lists archive-first persistence, stateless harness
  persistence, and sandbox work as if they have not landed

Concrete mismatches:

- Session: the spec still points to `agent/session/store.py` as the first
  durable implementation and says the target is to promote it to append-only,
  but `agent/session/archive.py` already exists and is the real durable path
- Harness: the spec says stateless harness + `wake` is not shipped, but the
  runtime is much closer to this now
- TUI: the spec says event-consumer status is shipped; that is now true in a
  stronger sense than the older doc wording implies
- Sandbox: the spec still frames isolation as mostly future work, while the
  runtime now provisions session sandboxes and auto-prefers Docker

Why this matters:

- the design doc is now behind the code, which makes architectural review and
  future gap tracking noisy

Recommended fix:

- rewrite §2, §8, and §9 of `design-spec.md` to reflect what is actually
  shipped today and move remaining gaps into a smaller forward-looking section

### 2. Eval Suite Semantic Drift

Status: open

What is wrong:

- the T1 names and semantics in `eval-suite.md` do not match the implemented
  T1 test suite exactly

Concrete mismatches:

- `eval-suite.md` defines:
  - T1.7 `universal_execute_contract`
  - T1.8 `approval_persists_across_restart`
  - T1.9 `orchestration_enforces_limits_externally`
- `tests/test_t1_managed_agent_properties.py` currently implements:
  - T1.7 approval persists and resumes
  - T1.8 step-limit enforcement
  - T1.9 orchestration externalization

What is missing as a result:

- no explicit T1 test for the universal hands contract
- no explicit approval-persist-after-restart case with the numbering and
  semantics the eval doc describes

Why this matters:

- the repo now has a T1 suite, but it is not a clean one-to-one
  implementation of the documented release gate

Recommended fix:

- either update `eval-suite.md` to the implemented T1 semantics, or rename and
  extend the T1 tests so the doc and the suite match exactly

### 3. Universal Hands Contract Is Still Not Fully Landed

Status: open

What exists:

- `ToolDispatch` gives one runtime dispatcher for registered tools
- built-in tools and skill tools share the same registry path

What is still missing relative to the design spec and eval suite:

- no explicit `execute(name, input) -> str` public contract across
  built-in tool, MCP-backed tool, and resource paths
- `ToolDispatch.execute()` still takes a `ToolCall` and returns `ToolResult`
  rather than the simpler universal string contract described in the spec
- there is no explicit contract test for native tool vs. MCP tool vs. resource
  parity

Why this matters:

- this is the main remaining design-spec gap in the “hands” model
- it is also the unimplemented eval-suite T1.7 claim

Recommended fix:

- add a thin universal `execute(name, input)` adapter layer and a T1 contract
  test covering at least one native tool, one MCP-backed tool path, and one
  resource-like path

### 4. T1 Coverage Exists, But Some Cases Are Weaker Than The Eval Doc Requires

Status: partial

What exists:

- append-only archive behavior
- replay, wake, approval persistence, sandbox lifecycle, and orchestration
  boundaries all have tests

What is still weak:

- T1.2 replay reconstruction test currently checks that events replay and that
  some user/state events are present; it does not assert full reconstructed
  equivalence of messages, loaded skills, and pending approvals
- T1.3 crash recovery test wakes from archive, but it does not prove the
  documented “kill mid-run and continue without repeating completed tool calls”
  semantics
- T1.5 sandbox credential isolation is good for env scrubbing, but it does not
  yet demonstrate blocked reads of host credential files like `~/.aws/credentials`
- T1.6 sandbox disposability is tested for local cleanup / Docker lifecycle,
  but not for process or file carryover in a real isolated backend

Why this matters:

- the architecture is better than before, but the proof burden in the test suite
  still falls short of the full eval-suite language

Recommended fix:

- strengthen the T1 tests to match the doc semantics exactly instead of just
  approximating them

### 5. Sandbox Isolation Is Stronger, But Still Not Absolute

Status: partial

What exists:

- session-owned sandboxes
- Docker-backed sandbox implementation
- local fallback with scrubbed env and disposable HOME
- runtime routes tool execution through the session sandbox context

What is still missing relative to the strict design target:

- if Docker is unavailable, the runtime falls back to `LocalSandbox`, which is
  not a true isolated execution boundary
- the design spec talks about containerized / VM-backed isolation as the target
  security posture, and that is still conditional rather than guaranteed

Why this matters:

- the architecture seam is right, but the strongest isolation mode is not
  universal on every host

Recommended fix:

- decide whether local fallback is acceptable product behavior or whether the
  runtime should fail closed when isolated backends are unavailable

### 6. T2 Coverage Is Broader, But Still Uneven Against The Eval Suite

Status: partial

What exists:

- T2 ability / difficulty metadata now exists in scenario cases
- the comparator computes weighted ability scores and cliff detection
- scenario counts are materially broader than before

Current scenario breadth:

- `core_agent`: 14 cases
- `research_and_report`: 6 cases
- `stock_strategy`: 9 cases

What is still missing:

- not all T2 abilities have easy / medium / hard triplets
- some abilities have only one or two represented difficulty bands
- the long-task additions from the eval doc are not implemented:
  - LT1 checkpoint / resume
  - LT2 trace legibility
  - LT3 partial-progress value

Examples of unevenness:

- `input_robustness` currently has only light coverage
- `self_monitoring` is still concentrated in hard cases
- `cost_time_bounds` is not represented as a full easy/medium/hard family
- `safety_under_pressure` does not yet have a strong hard case matching the doc

Why this matters:

- the runner can now score T2 more intelligently, but the underlying matrix is
  still smaller than the eval-suite contract

Recommended fix:

- finish the missing ability bands before claiming the T2 matrix is aligned with
  the eval doc

### 7. T3 Exists In Pieces, But Not Yet As A Clean Dedicated Regression Layer

Status: partial

What exists:

- skill pre-load behavior has unit coverage
- retrieval policy exists in runtime services
- approval behavior is exercised in runtime tests
- trace richness is implemented
- comparator supports baseline-gated regressions

What is still missing:

- no explicit T3 scenario or metric layer named and grouped the way the eval
  doc defines it
- no dedicated regression report for:
  - T3.1 skill pack pre-load by intent
  - T3.2 retrieval policy routing
  - T3.3 approval allow/ask/deny
  - T3.4 trace richness

Why this matters:

- the functionality exists, but the eval suite still treats T3 more explicitly
  than the codebase does

Recommended fix:

- add explicit T3 evaluators or at minimum a dedicated T3 regression suite that
  maps directly onto the four documented T3 claims

### 8. Release Gate Enforcement Exists In The Runner, But Not At Repo Level

Status: partial

What exists:

- `eval/runner.py` can load a baseline, compare against it, print a regression
  gate report, and exit non-zero on failure

What is still missing:

- no visible repo-level CI workflow or release pipeline wiring that makes this
  an actual enforced gate
- no obvious single command / documented release path that runs:
  - T1 hard gate
  - T2/T3 regression gate
  - budget hard-fail checks

Why this matters:

- the gate logic is present, but the repo does not yet show it being enforced
  as a release policy

Recommended fix:

- wire the eval runner and T1 suite into a documented release target and CI

### 9. Legacy JSON Store Surface Still Creates Conceptual Noise

Status: partial

What exists:

- the runtime path is archive-first

What is still present:

- `SessionStore` remains in the repo
- runtime / orchestrator constructors still accept `session_store`
- tests still instantiate `SessionStore` even when archive is the actual source
  of truth

Why this matters:

- this no longer looks like a critical architecture gap, but it still makes the
  mental model less crisp than it could be

Recommended fix:

- either demote `SessionStore` to compatibility-only status explicitly or
  remove it from the main runtime surfaces

## Recommended Next Priority

If the goal is to align the repo with the docs rather than just improve the
architecture further, the next best order is:

1. update `design-spec.md` so it reflects the actual shipped architecture
2. align `eval-suite.md` and the T1 suite numbering / semantics
3. implement and test the universal hands contract
4. fill missing T2 ability bands and long-task additions
5. make T3 an explicit regression suite instead of scattered tests
6. wire the release gate into CI / a documented release command
7. trim or clearly quarantine the remaining `SessionStore` surface

## Bottom Line

The codebase is in much better shape than the earlier gap refresh suggests.

The old “big architecture gaps” have mostly been reduced to:

- a strict universal-hands contract gap
- incomplete eval-suite alignment
- incomplete release enforcement
- documentation that is now behind the implementation

So the next refresh should be less about building new runtime seams and more
about making the **docs, tests, and release gate tell the same story as the
code**.
