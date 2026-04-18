# Gaps Review — Post-Refactor (2026-04-18)

A code-level audit of the current working tree against `doc/design-spec.md` and
`doc/eval-suite.md`, written after the refactor-plan items were landed.  This
doc replaces `gaps-review-2026-04-18.md` as the current state of record.

Previous gaps that are now **closed** are marked ✅.  Remaining items are
prioritised and include explicit "done" criteria so a reviewer can verify
completion without reading implementation code.

---

## Closed in This Cycle

| # | Gap | What Closed It |
|---|---|---|
| 1 | CI uses `pip install -r requirements.txt` (doesn't exist) | ✅ CI now uses `uv sync --extra dev`; no `requirements.txt` needed. |
| 2 | `SessionStore` described as "deprecated legacy" but still present | ✅ Refactored into typed `Protocol` + `SqliteSessionStore` wrapper over the archive. Design-spec §8 updated. |
| 3 | Duplicate recovery logic in `orchestrator.resume_runtime` vs `wake()` | ✅ `resume_runtime` now delegates to `wake()`. Single reconstruction path. |
| 4 | Route module too broad — `sessions_routes.py` mixed CRUD, turns, SSE, artifacts | ✅ Split into `sessions_routes`, `turns_routes`, `events_routes`, `artifacts_routes`, `auth_routes`, `skills_routes`. |
| 5 | `session_support.py` mixed Pydantic models, ownership helpers, and runner construction | ✅ Runner construction moved to `backend/apex_server/runner.py`. `session_support.py` only has models + `owned_session`. |
| 6 | `token_tracker.py` and `cost_tracker.py` as separate files | ✅ Consolidated into `core/src/agent/runtime/tracking.py`. Old files preserved as backward-compatible re-exports. |
| 7 | `StreamEnd` semantics undocumented — SSE closes or turn boundary? | ✅ Documented in `events_routes.py` docstring and `web-platform-plan.md` §7.1: `StreamEnd` = turn boundary; SSE re-subscribes. |
| 8 | `SessionOut` typo (`context` → `context_strategy`) in `owned_session` | ✅ Fixed. |

---

## Still Open — Design-Spec Alignment

### D1. Docker isolation test is static-only (no real container in CI)

**Spec:** §2.3 — "credentials never live inside the sandbox."

**Current state:** T1.5 includes an argv-inspection test that proves `DockerSandbox.provision()` does not forward host env vars.  But CI cannot run Docker, so there is no full integration test that provisions a container, runs a command inside it, and asserts credential files are absent.

**What "done" looks like:**
- CI job (or nightly job on a Docker-capable runner) that runs `test_t1_5` with `DockerSandbox` in a real Docker daemon.
- Alternatively: a self-hosted runner with Docker available.

**Priority:** Medium.  The argv proof is strong; full integration is defense-in-depth.

---

### D2. Benchmark regression gate is opt-in

**Spec:** §7.5 + eval-suite release gate #4.

**Current state:** `.github/workflows/ci.yml` runs the benchmark gate only when
`APEX_CI_RUN_BENCHMARK=1` is set as a repo variable.  A stub baseline exists at
`core/src/eval/baselines/core_agent.json` but contains zero results.

**What "done" looks like:**
- API credentials provisioned as GitHub secrets.
- A baseline generated from a real run checked into `core/src/eval/baselines/`.
- `APEX_CI_RUN_BENCHMARK=1` set as a repo variable so the gate runs on every PR (or at least on `main` pushes).

**Priority:** Medium.  The T1/T3/unit gates are enforced; this is the missing cost/quality gate.

---

### D3. Runtime module sprawl — further collapse possible

**Spec:** §9 roadmap item 3 — "collapse `loop, managed_runtime, orchestrator, shared_runner` into a tighter set."

**Current state:** The orchestrator now delegates recovery to `wake()` and
tracking is consolidated, but the runtime package still has 14 modules:

```
__init__.py, cost_tracker.py (re-export), guards.py, loop.py,
managed_runtime.py, orchestrator.py, sandbox.py, shared_runner.py,
token_tracker.py (re-export), tool_context.py, tool_dispatch.py,
trace.py, tracking.py, wake.py
```

Of these, `cost_tracker.py` and `token_tracker.py` are now one-line re-exports, and `loop.py` is a thin wrapper over `orchestrator.create_runtime`.  The next collapse step would merge `loop.py` into `orchestrator.py` and remove the re-export stubs.

**What "done" looks like:**
- `loop.py` eliminated; `run_agent` and `create_session` become module-level functions on `orchestrator.py` or a new `harness.py`.
- Re-export stubs removed once all external callers are migrated.
- Runtime package down to ≤9 source modules (excluding `__init__.py`).

**Priority:** Low.  Functional; purely a readability/maintenance improvement.

---

### D4. `SharedTurnRunner` is the only external consumer of the harness — server owns sessions

**Spec:** §4 — "Frontends plug in as consumers of the session event stream."

**Current state:** `SharedTurnRunner` holds an in-process runtime reference per session in `AppState.runners`.  This is fine for the MVP but means the server process is a single point of state — no horizontal scaling without swapping for a worker pool.

**What "done" looks like:**
- Phase 3 of the web-platform-plan: turn execution moves to Arq/Celery workers; SSE edge only streams events.
- Until then, `AppState.runners` is an explicit MVP trade-off documented in `deps.py`.

**Priority:** Low (post-MVP scaling concern).

---

### D5. No real MCP tool connector yet

**Spec:** §6 — hands split into Tools and Skill Packs; MCP is listed as a reachability target for `execute(name, input) -> str`.

**Current state:** `ToolDispatch` can register any async callable.  The `execute_by_name` contract is tested for native, MCP-stub, and resource-stub implementations.  But there is no real MCP server connector (stdio/SSE transport, tool discovery, capability negotiation).  Adding one is straightforward because the dispatch layer already normalises everything to `str`.

**What "done" looks like:**
- An `MCPConnector` class that discovers tools from an MCP server config, proxies calls through `ToolDispatch.execute_by_name`, and handles lifecycle (start/stop server process).
- At least one integration test with a mock MCP server.

**Priority:** Medium when the first MCP integration is needed; not a gap until then.

---

## Still Open — Eval-Suite Alignment

### E1. T1.3 — crash recovery test does not simulate a mid-run kill boundary

**Eval suite:** "Kill the harness mid-run (after at least one tool call). Call `wake(session_id)` with a fresh harness instance. The run continues from the last emitted event without repeating completed tool calls."

**Current state:** T1.3 now checks `tool_call_id` matching — it proves every
completed tool call has a corresponding tool message in the rehydrated history.
What it *doesn't* do is simulate an actual mid-run kill (e.g. `asyncio.cancel()`
or_SIGTERM) and then prove a *continuation* run doesn't re-execute already-completed
calls.  The test creates a completed session and verifies wake reconstruction,
which is close but not the exact "kill + resume" scenario from the eval suite.

**What "done" looks like:**
- A test that starts a multi-step run, cancels it after the first tool call
  completes, then calls `wake()` + `resume_pending()` or `start_turn()` and
  asserts the second turn does not re-invoke the first tool.

**Priority:** High — this is a core claim of the managed-agent architecture.

---

### E2. T1.5 — no real Docker integration test in CI

Covered in **D1** above.  An integration test inside a real container would also
satisfy the eval-suite's "sandbox_credential_isolation" proof at the hard
level (current proof is medium — LocalSandbox env scrubbing + Docker argv
inspection, but not a live container).

**Priority:** Medium.

---

### E3. T1.7 — universal hands parity proof covers str-return, not timeout/error shape parity

**Eval suite:** "Call a native tool, an MCP-backed tool, and a resource through the same `execute(name, input) -> str` interface. All three obey identical contracts for: input shape, return type, error format, timeout behavior."

**Current state:** `test_t1_tool_dispatch_contract.py` (12 tests) covers:
- success returns str for native, MCP-stub, resource-stub
- handler exceptions are caught and returned as str errors
- unknown tools return str errors (not exceptions)
- `asyncio.TimeoutError` propagates identically through `asyncio.wait_for` for all backends
- sync and async handlers are interchangeable
- arg validation errors are str, not exceptions

**What's still missing:**
- A test that verifies the *shape* of error strings is consistent across layers (native vs MCP vs resource) — e.g. all include the tool name, all have a "retry hint" format.
- A test that verifies a *real* timeout (handler that sleeps for 10s) is caught at the same timeout value regardless of backend.

**What "done" looks like:**
- Add 2 tests to `test_t1_tool_dispatch_contract.py`: one for error format shape parity, one for real timeout consistency.

**Priority:** Low.  The contract is already strong; this is tightening proof depth.

---

### E4. T2 — LT1 / LT2 / LT3 runner hooks are descriptive, not enforced

**Eval suite:** §T2 long-task additions define LT1 (checkpoint/resume at
step 25), LT2 (trace legibility scored by human), LT3 (cancel at 70% yields
partial-progress value).  The `tier` field on scenario test cases is metadata
only; the eval runner does not enforce kill/resume or cancel behaviour.

**Current state:** The test_cases.json files carry `tier: LT1` / `tier: LT3`
markers but the evaluators and runner treat them as descriptive labels, not
as test behaviour triggers.

**What "done" looks like:**
- `eval/runner.py` detects `LT1` tier and injects a `cancel` at the midpoint, then calls `wake()` for continuation.
- `eval/runner.py` detects `LT3` tier and cancels at 70% completion, then scores partial artifacts.
- LT2 (human-rated trace legibility) is documented as out of scope for automated CI and requires a manual review process.

**Priority:** High for LT1 (it's a core managed-agent claim); Medium for LT3; Low for LT2 (manual by design).

---

### E5. T2 scenario matrix gaps

**Eval suite:** Each ability should have easy/medium/hard cases in each scenario pack.

**Current state:**
- `core_agent/test_cases.json` has good coverage but `self_termination` is missing a hard case.
- No LT2 (trace legibility) case exists.
- `research_and_report` and `stock_strategy` packs are lopsided in ability/difficulty coverage.

**What "done" looks like:**
- Every ability has at least easy + medium; hard is needed for abilities where
  we want a cliff-detection signal.
- LT2 documented as manual-only.

**Priority:** Medium.

---

### E6. T2 scoring not yet computed in CI

**Eval suite:** "Per ability: `score = 0.2 * easy + 0.3 * medium + 0.5 * hard`."

**Current state:** `eval/comparator.py` and `eval/metrics.py` compute raw scores
per case.  The weighted T2 ability score and cliff detection (`medium - hard > 0.4`)
are not wired into the benchmark runner's pass/fail output.

**What "done" looks like:**
- `eval/runner.py` outputs a per-ability score table.
- `eval/comparator.py` flags abilities with cliff > 0.4.
- CI benchmark gate fails on cliff detection.

**Priority:** Medium (after a real baseline exists).

---

## Summary: Priority-Ordered Action Items

| Priority | Item | Spec reference | Section above |
|---|---|---|---|
| **P0** | Add mid-run kill + wake continuation test (T1.3 proof) | eval-suite T1.3 | E1 |
| **P0** | Implement LT1 runner hook in eval runner | eval-suite T2.LT1 | E4 |
| **P1** | Wire benchmark baseline + CI credentials so regression gate runs on PRs | design-spec §8 | D2 |
| **P1** | Add error-format parity test to T1.7 | eval-suite T1.7 | E3 |
| **P1** | Provision a Docker-capable CI runner for full sandbox isolation test | design-spec §2.3 | D1 |
| **P2** | Fill T2 scenario matrix gaps (hard self_termination, LT2 documentation) | eval-suite T2 | E5 |
| **P2** | Wire T2 ability scoring + cliff detection into eval runner | eval-suite T2 scoring | E6 |
| **P3** | Collapse `loop.py` into orchestrator; remove re-export stubs | design-spec §9 | D3 |
| **P3** | Build MCP connector when first MCP integration is needed | design-spec §6 | D5 |
| **P3** | Document `AppState.runners` as MVP-only scaling constraint | web-platform-plan §4 | D4 |

---

## For Team Review

The items above are what remains between **current code** and **full alignment with the design spec and eval suite**.  The managed-agent core shape (session → harness → wake → sandbox → tools → approval → events) is solid and shipped.  The gaps are now primarily in **proof depth** (T1.3 mid-run kill, T1.5 real Docker, T1.7 error parity) and **CI enforcement** (benchmark gate, LT1/LT3 hooks), not in architecture.

If you pick one thing to do next, make it **E1** — the mid-run kill + wake continuation test.  It is the most important proof gap in the managed-agent story.