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
- `agent/runtime/tool_dispatch.py:125`
- `tests/test_t1_managed_agent_properties.py:470`
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
- `tests/test_t1_managed_agent_properties.py:228`
- `tests/test_t1_managed_agent_properties.py:275`
- `tests/test_t1_managed_agent_properties.py:353`
- `doc/eval-suite.md:26`

### 4. Sandbox Isolation: Conditional Strong Mode, Local Fallback Still Exists

- `create_session_sandbox()` chooses Docker if available, otherwise LocalSandbox.
- A "fail closed" path exists when `sandbox_require_isolation=True`, which is good, but it still means strict isolation is not universal by default.

Pointers:
- `agent/runtime/sandbox.py:289`
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
- `scenarios/core_agent/test_cases.json:1`
- `scenarios/research_and_report/test_cases.json:1`
- `scenarios/stock_strategy/test_cases.json:1`
- `doc/eval-suite.md:160`

Also note:
- The evaluators do not currently treat `tier: LT1/LT3` as special semantics; they're just metadata unless the runner/evaluator enforces "kill and resume" or "cancel and partial value" behavior.

Pointers:
- `scenarios/core_agent/evaluator.py:32`

### 6. Release Gate "Runner-Level" Logic Exists, But Repo-Level Enforcement Is Partial

- CI runs T1/T3/unit tests, but it does not run the benchmark runner baseline/regression gate path (`eval/runner.py` + comparator baseline).
- The "regression gate" described in docs (baseline comparison, budget hard-fail) is not wired into `.github/workflows/ci.yml`.

Pointers:
- `eval/runner.py:1`
- `eval/comparator.py:1`
- `.github/workflows/ci.yml:1`

### 7. Legacy `SessionStore` Surface Still Present

- `SessionStore` is marked deprecated, but remains in constructor signatures and tests still instantiate it.
- This keeps conceptual noise alive and makes it harder to say "archive-only surfaces" are cleanly landed.

Pointers:
- `agent/session/store.py:1`
- `agent/runtime/managed_runtime.py:113`
- `agent/runtime/orchestrator.py:28`

## Notes On Local Verification

This review is primarily source-based (read + trace of code paths).
Local test execution in this environment was blocked by missing Python deps and `uv` cache permission issues, so this doc intentionally does not claim "tests pass".

