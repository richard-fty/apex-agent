# Gaps Review (2026-04-18)

This doc is a quick, actionable snapshot of what still looks *missing or weak*
relative to `doc/archived/gap-refresh-v2.md`, `doc/design-spec.md`, and `doc/eval-suite.md`,
based on a code read of the current working tree.

It focuses on gaps that block claiming "refresh-v2 is filled" with high confidence.

## Key Remaining Gaps / Issues

### 1. CI / Release Gate Wiring Is Not Actually Runnable Yet

- `doc/design-spec.md` claims CI release gate is shipped, but the workflow installs via `pip install -r requirements.txt`.
- This repo uses `pyproject.toml` and has **no** `requirements.txt`, so CI will fail immediately.

Pointers:
- `.github/workflows/ci.yml:24`
- `pyproject.toml:1`

What "done" looks like:
- Update CI to use `uv`/PEP-517 install, or add a generated `requirements.txt` (and keep it in sync).

### 2. "Universal Hands" Exists, But Parity Proof Is Still Weak

- `ToolDispatch.execute_by_name(name, input) -> str` exists (good).
- T1 tests cover only "native tool" + two registry stubs labeled MCP/resource. They do not prove parity for:
  - timeout behavior
  - error format shape across layers
  - real MCP-backed tool path (connector/server), and real resource-like access path

Pointers:
- `core/src/agent/runtime/tool_dispatch.py:125`
- `core/tests/test_t1_managed_agent_properties.py:470`
- `doc/eval-suite.md:47`

What "done" looks like:
- A contract test that executes:
  - one real built-in tool
  - one real MCP tool (or at least a dedicated adapter boundary with consistent error/timeout semantics)
  - one resource-like tool path
  and asserts consistent return/error/timeout behavior.

### 3. T1 Proof Burden Still Lighter Than the Eval Doc Describes

The tests exist and are directionally right, but several are still "approximation" level:

- T1.2 replay reconstruction asserts ">= 1 message" and terminal state, not full reconstructed equivalence (messages, loaded skills, pending approvals).
- T1.3 crash recovery checks that tool messages are present after `wake()`, but it does not simulate an actual mid-run kill boundary and prove "no repeat" of completed tool calls at the execution layer.
- T1.5 credential isolation is mostly about LocalSandbox env scrubbing and HOME isolation; it does not demonstrate real host credential file blocking under a strict isolation backend.

Pointers:
- `core/tests/test_t1_managed_agent_properties.py:228`
- `core/tests/test_t1_managed_agent_properties.py:275`
- `core/tests/test_t1_managed_agent_properties.py:353`
- `doc/eval-suite.md:26`

### 4. Sandbox Isolation: Conditional Strong Mode, Local Fallback Still Exists

- `create_session_sandbox()` chooses Docker if available, otherwise LocalSandbox.
- A "fail closed" path exists when `sandbox_require_isolation=True`, which is good, but it still means strict isolation is not universal by default.

Pointers:
- `core/src/agent/runtime/sandbox.py:289`
- `config.py` (search `sandbox_require_isolation`)

Decision needed:
- Is LocalSandbox acceptable product behavior, or should the runtime require isolation in production by default?

### 5. T2 Matrix Improved, But Still Uneven Across the Repo

`scenarios/core_agent/test_cases.json` now covers many abilities across easy/medium/hard, and includes LT1/LT3 markers.
But remaining unevenness still exists:

- `self_termination` has easy+medium only (no hard).
- No LT2 ("trace legibility") case exists.
- Other scenario packs (`research_and_report`, `stock_strategy`) are still lopsided in ability/difficulty coverage.

Pointers:
- `core/src/scenarios/core_agent/test_cases.json:1`
- `core/src/scenarios/research_and_report/test_cases.json:1`
- `core/src/scenarios/stock_strategy/test_cases.json:1`
- `doc/eval-suite.md:160`

Also note:
- The evaluators do not currently treat `tier: LT1/LT3` as special semantics; they're just metadata unless the runner/evaluator enforces "kill and resume" or "cancel and partial value" behavior.

Pointers:
- `core/src/scenarios/core_agent/evaluator.py:32`

### 6. Release Gate "Runner-Level" Logic Exists, But Repo-Level Enforcement Is Partial

- CI runs T1/T3/unit tests, and now uses `uv sync --extra dev` (not `pip install -r requirements.txt`).
- The benchmark regression gate still requires `APEX_CI_RUN_BENCHMARK=1` and is not enforced on every PR.

Pointers:
- `core/src/eval/runner.py:1`
- `core/src/eval/comparator.py:1`
- `.github/workflows/ci.yml:1`

### 7. Legacy `SessionStore` Surface — Evolved, Not Removed

- `SessionStore` was described as "deprecated" in earlier reviews. It has been refactored into a typed `Protocol` + `SqliteSessionStore` wrapper that delegates to `SessionArchive`.
- The old JSON-file impl has been removed. The current `store.py` is now the proper CRUD layer for session metadata, with `list_events` and `append_event` bridging typed event access over the archive.
- The design spec now correctly describes it as a typed protocol wrapper rather than a "removed" artifact.

Pointers:
- `core/src/agent/session/store.py:1`

### 8. Route and Runtime Cleanup — Completed

- `sessions_routes.py` has been split into focused modules: `sessions_routes.py`, `turns_routes.py`, `events_routes.py`, `artifacts_routes.py`, `auth_routes.py`, `skills_routes.py`.
- `session_support.py` now contains only Pydantic models and ownership helpers. Runner construction has been extracted into `backend/apex_server/runner.py`.
- `SessionOrchestrator.resume_runtime` has been consolidated to delegate to `wake()`, eliminating duplicate recovery logic.
- `token_tracker.py` and `cost_tracker.py` have been consolidated into `tracking.py` with backward-compatible re-exports.

Pointers:
- `backend/apex_server/runner.py`
- `backend/apex_server/routes/session_support.py`
- `core/src/agent/runtime/orchestrator.py`
- `core/src/agent/runtime/tracking.py`

### 9. SSE / Stream-end Semantics — Resolved

- `StreamEnd` is formally a **turn boundary**, not a connection close. The SSE handler re-subscribes after `StreamEnd` to receive the next turn's events on the same HTTP connection.
- Reconnection uses `Last-Event-ID` to replay persisted events, then attaches to the live bus.
- This decision is documented in `events_routes.py` and `doc/web-platform-plan.md` §7.1.

### 10. Remaining Gaps (Updated)

- T1.5 still cannot run real Docker in CI.
- Benchmark-regression-gate in CI remains opt-in.
- T1 test depth: T1.2 now asserts full message equivalence; T1.3 now checks tool_call_id matching; but a full mid-run kill + resume boundary test is still needed.
- Universal hands parity proof: the T1.7 test covers native, MCP-stub, and resource-stub paths for the str-return contract, but doesn't yet verify consistent timeout/error behavior across layers.
