# MVP Cuts: Coding Ability Regression Harness

Companion to `coding-ability-regression-harness.md`. That doc stays as the long-term vision. This doc lists exactly what to build first, what to cut, and how to leverage the existing repo so we ship a working loop in 1–2 weeks instead of 4–6.

## 0. North Star for MVP

**Prove the loop end-to-end on three cases.** The agent receives a coding prompt, edits files in a sandbox, builds, boots, a Playwright check passes, scores are written. Everything else is Phase 2+.

Product model for the MVP:

```text
Session
  -> Task
    -> TodoItem
    -> Event
    -> Artifact
```

Implementation mapping for the MVP:

```text
Session   = existing session_id / SessionRecord
Task      = existing turn_id, exposed as task_id in UI/API language
TodoItem  = existing PlanStep payload, renamed conceptually
Event     = existing SessionArchive event
Artifact  = existing FilesystemArtifactStore artifact
Run       = do not add
Attempt   = do not add
```

Pass criteria for "MVP done":
- 3 eval cases run via `python -m eval.runner --scenario coding`
- Same harness runs in `--replay` mode in CI without agent/API keys, but with Docker (frozen patch + golden gates)
- Frontend shows live preview iframe + todo checklist + terminal log artifact
- One CSV row per case: `case_id, install_passed, build_passed, test_passed, score, duration_sec, cost_usd`

That's it. No baseline comparison, no judge, no visual diff, no preview proxy, no Next.js.

## 1. Map to Existing Repo (Reuse, Don't Rebuild)

The original doc reads as greenfield. ~60% of it already exists. Before writing new code, map every concept:

| Doc concept | Existing module to reuse | New work |
|---|---|---|
| `Session` table | `SessionRecord` + `SessionArchive` (Postgres) | none |
| `events` table | already there via `SessionArchive.emit_event` | none |
| `artifacts` table + storage | `FilesystemArtifactStore` (`results/artifacts/{sid}/{aid}`) | none |
| Event bus + SSE replay | `EventBus`, `events_routes.py`, `Last-Event-ID` | none |
| `TodoItem` checklist | `PlanUpdated` event with `PlanStep[]` | rename/alias the product type to `TodoItem`; keep wire event compatible |
| `Task` as execution boundary | `turn_id` already groups events under a session | expose as `task_id` in product language; do not add a table yet |
| Sandbox abstraction | `BaseSandbox`, `LocalSandbox`, `DockerSandbox`, `create_session_sandbox()` | extend, don't replace |
| Trace + tool ledger | `Trace.tool_calls`, `Trace.total_usage`, `Trace.run_outcome` | add `Trace.artifacts`, `Trace.gate_results` |
| Scenario + evaluator | `Scenario` abstract class, `runner.run_single`, `mock_brain` | new `CodingScenario` subclass |
| Artifact rendering in UI | `ArtifactPanel` switch on kind | add `app_preview`; reuse `terminal_log`; render patch as `code` with `language: "diff"` |
| `app_preview` artifact kind | `ArtifactKind` enum (Python + TS) | add `app_preview` only |
| Backend artifact route | `artifacts_routes.py` | add CSP headers for `app_preview` |
| Mock-LLM CI mode | `eval/mock_brain.py` already supports it | add `--replay` mode for frozen-patch runs |
| Per-session sandbox lifecycle | `managed_runtime.py:191` calls `create_session_sandbox`; `provision()` lazily at line 1024–1026, `destroy()` paired at 274–275 | none — pairing verified |

**Rule:** if a row in the original doc isn't in the table above, scrutinize whether you actually need it for MVP.

## 2. Phase 1 Scope Cuts

The original Phase 1 (§15) lists 6 broad deliverables. Trim aggressively.

### Keep (MVP Phase 1)
Three core deliverables, plus two reuse items:

1. **Template + cases:** `vite-react` template at `core/src/scenarios/coding/templates/vite-react/` (unpacked fixture); three cases (two C1, one C2) sharing it.
2. **Gates pipeline:** install → build → test (test gate folds in runtime via Playwright `webServer`).
3. **Output:** CSV file `results/coding_eval_{timestamp}.csv` with one row per case.

Reused as-is (no new work):
- Artifact storage — `FilesystemArtifactStore`
- Event/SSE/session pipeline — already shipping

### Cut to Phase 2
- Next.js / `next-fullstack` template
- Preview proxy with unique subdomains
- Postgres results table for eval runs (CSV is enough)
- Judge scoring (LLM rubric)
- Visual diff scoring
- Baseline-vs-candidate dashboard UI

### Cut to Phase 3+
- gVisor / Kata / Firecracker
- Per-task TTL cleanup, quota enforcement
- S3 fixture bundles (`tar.zst`) — local unpacked dirs are fine
- Secret scanning, forbidden path enforcement at write time
- Multi-attempt / multi-run schema (`Run`, `Attempt` tables)

## 3. Specific Edits to the Original Doc

When you re-read `coding-ability-regression-harness.md`, treat the items below as overrides for MVP.

### §3 Product Model
- **Keep the product model as `Session -> Task -> TodoItem -> Event -> Artifact`.**
- **Do not create new `tasks`, `todo_items`, `events`, or `artifacts` SQL tables for MVP.** Implement them with existing `SessionArchive` + `FilesystemArtifactStore`.
- **Use `turn_id` as the backing identifier for `Task`.** In UI/API copy, it is fine to call it `task_id`, but do not add a separate task table yet. One coding eval = one task-backed turn. Add a persisted `tasks` table only if a single task needs multiple turns.

### §3.3 Todo Event Contract
- **Use `TodoItem` as the product name.**
- **Unified status vocabulary across the entire stack — 4 values, one definition:**
  ```python
  # core/src/agent/core/models.py — single source of truth
  TodoStatus = Literal["pending", "in_progress", "completed", "failed"]
  ```
  Imported by `planner.py`, `events/schema.py PlanStep`, frontend `types.ts`, and every scenario. No per-layer vocabulary, no runtime normalization.

  Status meanings:

  | Status | Meaning |
  |---|---|
  | `pending` | Not started |
  | `in_progress` | Running |
  | `completed` | Finished successfully |
  | `failed` | Anything that was not a success |

  Collapsing rules (one-time, on-load only — for legacy persisted data):
  - `done` → `completed`
  - `blocked` → `pending`
  - `cancelled` / `skipped` → `failed`

  Notes carry nuance. If a task is blocked, keep it `pending` and put the blocking reason in `note`. If a task was cancelled or skipped, mark it `failed` and put the reason in `note`.

- **Do not introduce new `todo_list_updated` / `todo_updated` events in the MVP.** Keep the existing `plan_updated` wire event for compatibility, but type its steps as todo items:
  ```python
  class TodoItem(BaseModel):
      id: str
      text: str
      status: TodoStatus

  PlanStep = TodoItem  # compatibility alias for existing plan_updated event
  ```
- Frontend reducer already handles `plan_updated`; render it as a TodoItem checklist, not as a generic "plan".
- Phase 2 can add `todo_items_updated` while continuing to accept `plan_updated` for replay compatibility.

### §6.1 Bundle Shape
- **Drop `tar.zst`.** Templates are unpacked directories under `core/src/scenarios/coding/templates/<name>/`. The harness `cp -r` into the sandbox workspace.
- **Drop `eval/playwright.spec.ts` inside the bundle.** Put the spec in the case definition, not the template — the template is shared across cases.

### §6.2 Execution Manifest
Keep, but trim:
```json
{
  "case_id": "vite_filter_list_001",
  "stack": "vite-react",
  "install": ["pnpm", "install", "--frozen-lockfile", "--prefer-offline"],
  "build": ["pnpm", "build"],
  "test": ["pnpm", "exec", "playwright", "test", "--reporter=json"],
  "health": {
    "url": "http://127.0.0.1:3000",
    "max_wait_sec": 30,
    "interval_sec": 0.5
  },
  "budget": {
    "max_steps": 30,
    "max_cost_usd": 0.50,
    "max_wall_sec": 300
  },
  "limits": {
    "memory_mb": 1024,
    "cpus": 1.0,
    "max_stdout_kb": 2048
  }
}
```

Removed: `serve` (Playwright owns its server in MVP), `network_policy` (now hardcoded by stage in §7.6 — install=on, everything-else=off), explicit pid/process limits (Docker defaults are fine for MVP).

Added: `budget` (cost/step/time caps — required to prevent runaway costs).

Network policy is **not configurable per case** — it's a property of the harness (see §7.6), not the manifest. This is intentional: cases can't accidentally weaken the eval validity contract.

### §7.1 Local Sandbox
- **Keep Colima + Docker** — your `DockerSandbox` already shells out to the docker CLI, so this works unchanged.
- **`SANDBOX_REQUIRE_ISOLATION=false`** in MVP `.env` so Mac dev without Colima falls back to LocalSandbox. Production flips this to `true`.
- **Bind-mount pnpm store from day one** (the original doc deferred this to Phase 4 — do not):
  ```python
  SandboxMount(source=os.path.expanduser("~/.local/share/pnpm/store"),
               target="/pnpm-store", read_only=False)  # install gate only
  ```
  Set `PNPM_STORE_DIR=/pnpm-store` in the manifest's install env. Mount it read-write for the install gate so first-run cache misses can populate it; build/test do not need the store.

### §7.4 Execution Stages and Sandbox Modes

Six stages per case, mapped to two distinct sandbox execution modes.

```
[1] prepare_workspace   — cp template into results/sandbox/{sid}/, init git
[2] agent_run           ← Mode A (long-lived container)
[3] install gate        ← Mode B (one-shot, network on)
[4] build gate          ← Mode B (one-shot, network off)
[5] test gate           ← Mode B (one-shot, network off; Playwright boots app)
[6] finalize            — git diff, write CSV, destroy Mode A container
```

#### Mode A — long-lived agent container
Used during `agent_run` only. One container per session.

```
docker run -d --name agent-{session_id} \
  --network none \
  --memory 512m --cpus 0.5 \
  -v results/sandbox/{sid}:/workspace \
  apex-sandbox:latest sleep infinity
```

- Lives the whole session; provisioned at session start, destroyed in `finalize`.
- `--network none` — agent must write code, not curl solutions (eval validity).
- Each tool call = `docker exec` into this container (~50ms, state preserved).
- Why: agent makes 30+ tool calls per case; cwd/env/scratch must persist between them.
- **Resource caps** shown above (`512m`, `0.5`) are MVP defaults for `agent_run`. Production reads `config.settings.sandbox_memory` / `sandbox_cpus`; the harness can override per-mode by passing explicit caps to `provision()`.

#### Mode B — one-shot gate containers
Used during install/build/test gates. Fresh container per stage.

```
docker run --rm --memory 1g --cpus 1 \
  --network <bridge|none> \
  -v results/sandbox/{sid}:/workspace \
  -v ~/.local/share/pnpm/store:/pnpm-store:rw \
  -e PNPM_STORE_DIR=/pnpm-store \
  apex-sandbox:latest sh -c "<stage_command>"
```

- Fresh container per stage, dies on exit (`--rm`).
- Network varies per stage: install gets `bridge`, build/test get `none`.
- `pnpm-store` is mounted only for the install gate and is writable there. Build/test read `node_modules` from the shared workspace.
- No state leaks between stages — each gate is a clean check.
- Why: per-stage network policy + hermetic gates.
- **Resource caps** (`1g`, `1`) are MVP defaults for gate stages; gates override the session-level `settings.sandbox_*` because they need more headroom than `agent_run`.

#### When the switch happens
Once per case, at the boundary between phase 2 and phase 3. The harness picks the method based on phase:

```python
# Phase 2 — agent_run, Mode A
result = await sandbox.run_command(tool_call.command, timeout=30)

# Phase 3 — gates, Mode B
result = await sandbox.run_oneshot(
    cmd=manifest[stage],
    network="bridge" if stage == "install" else "none",
    timeout=manifest["budget"]["max_wall_sec"],
)
```

Same `BaseSandbox` object, two methods. No flag, no mode toggle — phase decides.

#### Why two modes are required (not optional)
Trying to use a single mode breaks one of two properties:

| If we used... | What breaks |
|---|---|
| Mode A everywhere | Network is fixed at provision. Either install fails (no network) or agent has internet for the whole session (eval validity gone). |
| Mode B everywhere | Each tool call = new container. ~300ms cold start × 30 calls = 9 wasted seconds per case, and cwd/env/state is lost between calls. |

Two modes is the minimum.

#### Shared workspace = the handoff
Both modes bind-mount `results/sandbox/{session_id}/`. Mode A writes the agent's edits; Mode B reads/builds/tests them. That directory is the contract between phases.

### §7.5 Sandbox Performance Defaults
- Image: `apex-sandbox:latest`, prebuilt, `node:22-alpine` + pnpm + chromium baked in
- Image pull policy: `IfNotPresent`
- Always `--rm` on Mode B; explicit `destroy()` on Mode A
- Mounts:
  - `workspace`: `results/sandbox/{sid}/` (rw, bind)
  - `pnpm-store`: `~/.local/share/pnpm/store` (rw during install gate only)
  - `node_modules`: stays in the shared workspace for MVP so one-shot build/test containers can reuse dependencies installed by the install gate
  - `dist`: stays in the shared workspace for MVP so test artifacts and post-run inspection are straightforward
- Resource caps: agent_run 512m/0.5cpu; gates 1g/1cpu
- Health check: exponential backoff 100ms → `max_wait_sec`
- Stdout cap: 2MB per stage
- Concurrency: `max(1, physical_cpus // 2)` cases in parallel

### §7.6 Network Policy

**One rule:** network is on **only** during the install gate. Off everywhere else.

| Stage | Network | Why |
|---|---|---|
| prepare_workspace | off | local file copy |
| agent_run | **off (frozen)** | no capability bleed; agent must write code, not search |
| install gate | **on, scoped** | only stage that legitimately needs the registry |
| build gate | off (frozen) | deterministic build |
| test gate | off (frozen) | deterministic Playwright |
| finalize | off | git diff + CSV write |

Even the install gate is cache-first: with `--prefer-offline` and the bind-mounted pnpm store, the network is open but rarely touched after the first warm-up run.

**There is no flag to thaw the freeze.** Network policy is baked into the manifest per stage. If a future scenario needs network during agent_run (testing a real-API tool), it goes in a separate scenario class with documented validity caveats.

#### Why the freeze matters for regression validity
Four properties the freeze guarantees, all of which break under unrestricted network:

1. **Capability isolation** — score measures coding ability, not search/fetch ability.
2. **Determinism** — same agent + same case → same score, regardless of time of day or CDN state.
3. **Fixture stability** — pinned lockfile + offline cache means cases don't decay as registries drift.
4. **Baseline stability** — baseline from last month is still a valid comparison this month.

Without these, "candidate scored higher than baseline" means nothing — could be the agent, could be the network.

### §8 Frontend Cuts
- **Drop the dual-pane layout redesign.** The existing `ArtifactPanel` already does right-side artifact rendering; reuse it.
- **Drop `selectedArtifactId` state addition** — Zustand store already has `ui.artifactView`.
- **Rename UI copy from "Plan" to "Todo" / "Checklist".** The event can remain `plan_updated`, but the user-facing concept should be TodoItem.
- **Add only 1 artifact kind** to `frontend/src/types.ts` and `core/src/agent/artifacts/model.py`:
  - `app_preview` — iframe pointing at the preview server
- **`app_preview` content shape (verified: `Artifact` model has no `url` field):**
  - The artifact's stored *content* is the preview URL string (UTF-8). No new schema field.
  - `spec.kind = "app_preview"`, `spec.mime = "text/uri-list"` (or `"text/plain"`).
  - Content example: `http://127.0.0.1:3000` (just the URL, no JSON wrapper).
  - Frontend reads via the existing GET `/artifacts/{id}` route, then:
    ```tsx
    const previewUrl = artifact.content.trim();
    <iframe src={previewUrl} sandbox="allow-scripts allow-forms" />
    ```
  - Phase 2 (preview proxy) swaps in a unique-origin URL — same shape, no migration.
- **Reuse without adding kinds:**
  - `terminal_log` — already exists; render as `<pre>` from streamed `SandboxExecOutput` events
  - **patch as `code` with `language: "diff"`** — the existing `code` artifact kind passes through `SyntaxHighlighter`, which supports diff highlighting natively. No new artifact kind, no new dep (skip `react-diff-viewer-continued`).

### §9 Preview Cuts
- **Drop preview proxy + unique subdomain + TLS** for MVP. Use:
  - `localhost:3000` directly when running locally (dev-only)
  - For CI replay mode: capture screenshots via Playwright, render as `image` artifact (already supported)
- **iframe sandbox attribute** — drop `allow-same-origin` so the preview cannot share origin privileges with the parent. Apps that rely on localStorage may fail in MVP; document this limitation. Re-add `allow-same-origin` in Phase 2 only after the preview proxy gives each preview a separate origin.

### §10 Test Levels
- **Level 1 (deterministic gates):** keep all of `install / build / playwright_test`. Drop typecheck and lint as separate gates — they're caught by `pnpm build` for vite-react.
- **Level 2 (browser gates):** keep, but each MVP case ships one Playwright spec, not a suite.
- **Level 3 (judge):** **defer entirely to Phase 2.** No LLM judging in MVP.

### §10.0 (NEW) Replay/Mock Mode
Add this section to the long-term doc. For MVP, the harness needs three execution modes:

| Mode | What runs | When |
|---|---|---|
| `--live` | Agent + sandbox + gates | Manual local runs, nightly |
| `--mock` | Mock LLM (existing `mock_brain`) + sandbox + gates | Tests harness wiring |
| `--replay <case_id>` | No agent, apply that case's `golden_patch`, run gates only | CI on every PR |

`--replay` is the one CI uses. It tests the harness itself without burning tokens or LLM time. Each case ships a `golden/patch.diff` that's known to pass all gates. CI catches harness regressions, not agent regressions.

### §10.1 What Gates Actually Are

**The gates are the regression test.** There is no separate "evaluation step" — the gates execute the agent's code and *also* produce the pass/fail signal. They serve both jobs at once.

Each gate plays two roles simultaneously:

| Gate | What it runs | What pass/fail tells you about the agent |
|---|---|---|
| install | `pnpm install --frozen-lockfile --prefer-offline` | Did the agent leave `package.json` and lockfile consistent? |
| build | `pnpm build` (Vite production build) | Does the code compile? Type errors? Imports? Syntax? |
| test | `pnpm exec playwright test` (boots app via `webServer`) | Does the running app satisfy the case's behavior spec? |

**The test gate is where "starting the app" happens.** Playwright's `webServer` config boots `vite preview` before running the spec and tears it down after. No separate "serve" stage in MVP.

Per-case scoring derived directly from gate results:
```python
if not gate_results["install"]:
    score = 0.0   # install is a hard prerequisite
else:
    score = 0.4 * int(gate_results["build"]) + 0.6 * int(gate_results["test"])
```

Roll up across cases = the MVP CSV report. Baseline comparison starts in Phase 2.

**One-line:** gates run install/build/test on the agent's code, AND those gates' pass/fail results *are* the regression score. Same mechanical step, dual purpose.

### §11 Eval Case Format
Trim to MVP shape:
```json
{
  "id": "vite_filter_list_001",
  "title": "Add filter input to a list",
  "tier": "C2",
  "template": "vite-react",
  "prompt": "Add a search input above the list that filters items as the user types.",
  "allowed_paths": ["src/**", "package.json"],
  "playwright_spec": "tests/filter.spec.ts",
  "golden_patch": "golden/patch.diff",
  "manifest": { "...see §6.2..." }
}
```

Removed: `repo_bundle` (URL → local path), `success_criteria` (free-form text → encoded as Playwright assertions instead), `scoring` weights (fixed for MVP: build=0.4, browser=0.6).

`allowed_paths` enforced post-hoc on the diff, not at write time.

### §12 Regression Comparison
**Defer entirely.** First MVP runs produce the baseline by being tagged. Phase 2 introduces:
- Tagged baseline JSON: `results/baselines/v0.1.0.json`
- Comparison report: `python -m eval.compare v0.1.0 candidate`

For now, just print the CSV.

### §13 Eval Suite Tiers
- **MVP:** 2 C1 cases + 1 C2 case = 3 total.
- **Phase 2:** expand to 10 cases across C1/C2.
- **Phase 3:** add C3 (full-stack with Next.js).
- **Phase 4:** add C4 (long-horizon multi-turn).

### §14 Stored Artifacts
Cut to MVP-essential:
- Input prompt + manifest
- Tool call ledger (already in `Trace`)
- Final patch (`git diff`)
- Build log + Playwright JSON report
- Screenshots from Playwright (already produced)
- Cost / tokens / step count (already in `Trace.total_usage`)

Drop for MVP: Playwright video, network failure ledger, accessibility audits, sandbox policy decisions log.

## 4. New Work — File-Level Plan

### Backend / core
- **`core/src/agent/events/schema.py`** — introduce/rename `TodoItem`, keep `PlanStep` as a compatibility alias, and add `ArtifactKind.APP_PREVIEW`. No new event types for MVP.
- **`core/src/agent/artifacts/model.py`** — no enum ownership change; it imports `ArtifactKind` from `events/schema.py`. Patch is rendered as `code` with `language: "diff"`; `terminal_log` already exists.
- **`core/src/agent/runtime/trace.py`** — add `artifacts: list[dict]` and `gate_results: dict[str, bool]` fields. Reuse existing `Trace.save(directory)` for persistence; CSV is derived from these JSON files.
- **`core/src/agent/runtime/sandbox.py`** — keep `run_command(cmd, timeout)` for Mode A long-lived agent execution. Add `run_oneshot(cmd, timeout, network)` for Mode B gate containers so install can run with network while build/test stay frozen.
- **`core/src/agent/runtime/managed_runtime.py`** — no change needed for sandbox lifecycle. `provision/destroy` pairing already in place (provision lazy at 1024–1026, destroy at 274–275, guarded by `_sandbox_provisioned` flag).
- **`core/src/skill_packs/coding/`** — new skill pack with two tools:
  - `apply_patch(patch)` — applies a unified diff to the workspace; emits artifact via existing `emit_artifact_created/append/finalized` helpers from `tool_context.py`
  - `update_plan(steps)` — emits `PlanUpdated` (existing event)
  - Plus standard `read_file`, `write_file`, `run_command` from existing `tools/`
  - Declares `keywords = ["code", "build", "vite", "react", "typescript", "frontend", "app", "fix", "implement", ...]` so the existing `SkillLoader.pre_load_by_intent()` auto-loads it on coding prompts.
- **`core/src/scenarios/coding/`** — new scenario:
  - `scenario.py` — `CodingScenario(Scenario)` with `evaluate(trace, case)` that reads `trace.gate_results`
  - `templates/vite-react/` — unpacked starter (package.json, lockfile, src/, playwright.config.ts with `webServer`)
  - `cases/case_001.json`, `case_002.json`, `case_003.json`
  - `cases/case_001/tests/*.spec.ts` — per-case Playwright spec(s) referenced by `playwright_spec` in the case JSON
  - `cases/case_001/golden/patch.diff` — frozen patch known to pass all gates, used by `--replay <case_id>`
- **`core/src/scenarios/registry.py`** — one-line registration block alongside `wealth_guide` and `lt1_equity_briefing`.
- **`core/src/eval/runner.py`** — extend with:
  - Stage runner: `prepare_workspace → agent_run → gates → finalize`
  - `--replay <case_id>` mode that skips `agent_run`
  - Budget enforcement (max_steps / max_cost / wall_sec)
  - CSV writer that flattens existing `Trace.save()` JSON files — does not invent a new persistence path

### Sandbox image
- **`core/sandbox/Dockerfile`** (new) — produces `apex-sandbox:latest`. Base `node:22-alpine`; pre-baked `pnpm` (via corepack), Playwright + chromium (`pnpm dlx playwright install --with-deps chromium`), non-root user, `WORKDIR /workspace`. Built once with `docker build -t apex-sandbox:latest .`; CI builds and caches it.

### Backend server
- **`backend/apex_server/routes/artifacts_routes.py`** — add CSP headers when `kind == "app_preview"`.

### Frontend
- **`frontend/src/types.ts`** — add `app_preview` to `ArtifactKind`; introduce `TodoItem` and keep `PlanStep = TodoItem` compatibility.
- **`frontend/src/components/artifacts/ArtifactPanel.tsx`** — add only one new render case:
  - `app_preview` → read the preview URL from `artifact.content.trim()` and render `<iframe src={previewUrl} sandbox="allow-scripts allow-forms" />` (no `allow-same-origin` in MVP)
  - Patches: emit as `code` artifact with `language: "diff"`; existing `SyntaxHighlighter` handles the diff coloring with no new dep.
  - `terminal_log` → existing or simple `<pre>`, fed by `SandboxExecOutput` events streamed over SSE.
- **`frontend/src/components/chat/PlanCard.tsx`** — rename user-facing copy to Todo/Checklist and render `TodoItem[]` from store as a checkbox list driven by `item.status`. Keep the existing store field if that avoids churn.

### CI
- `.github/workflows/coding-eval.yml` — runs `python -m eval.runner --scenario coding --replay` for every case. No agent, no API keys. Docker is required (the gates run in `apex-sandbox:latest`); the workflow builds the image from `core/sandbox/Dockerfile` with layer caching.
- **Failure criterion:** the workflow asserts every replay case scores `1.0` (all three gates pass against the golden patch). Any case scoring below `1.0` fails the workflow. This catches harness regressions, not agent regressions.

## 4.5 Existing Plumbing You're Wiring Into

Before writing new modules, confirm you're using these existing pieces. Each one was a place the original doc wanted to reinvent.

| Existing piece | Use it for | File |
|---|---|---|
| `SandboxExecStarted/Output/Finished` events | Live-stream gate stdout/stderr to the `terminal_log` artifact via SSE | `core/src/agent/events/schema.py` |
| `ApprovalRequested/Resolved` events | Network-on install gating — eval runner auto-approves; interactive UI prompts the user. Don't build a new gating layer. | `core/src/agent/events/schema.py` |
| `tool_context.emit_artifact_created/append/finalized` | All artifact emission from `apply_patch`, `app_preview`, build logs | `core/src/agent/runtime/tool_context.py` |
| `Trace.save(directory)` | Trace JSON persistence; CSV is derived, not a parallel store | `core/src/agent/runtime/trace.py` |
| `config.settings.sandbox_*` | Sandbox tuning — reference typed settings (`sandbox_require_isolation`, `sandbox_memory`, `sandbox_cpus`, `sandbox_docker_image`, `sandbox_network`), not raw env-var spelling | `core/src/config.py` |
| `SkillLoader.pre_load_by_intent` | Auto-load coding skill on coding prompts — driven by the skill's `keywords` list | `core/src/agent/skills/loader.py` |
| `scenarios/registry.py` discovery | Register `CodingScenario` here alongside existing scenarios | `core/src/scenarios/registry.py` |
| `SessionArchive` event log + `FilesystemArtifactStore` layout | Workspace dir = `results/sandbox/{session_id}/` to mirror `results/artifacts/{session_id}/`; same gitignore, same cleanup story | `core/src/agent/session/archive.py`, `core/src/agent/artifacts/store.py` |
| `SyntaxHighlighter` with `language="diff"` | Patch rendering — no diff-viewer dep | `frontend/src/components/...` |
| Existing `useSSE.ts` + Zustand `ingest()` | Frontend event ingestion — no changes needed; new events flow through automatically | `frontend/src/hooks/useSSE.ts`, `frontend/src/store.ts` |

**Rule:** if you find yourself writing a module that overlaps with a row above, stop and use the existing one.

## 5. Order of Work (1–2 weeks)

Day 1–2: align schemas (`TodoItem` alias for existing `PlanStep`, `ArtifactKind`), add `Trace.gate_results`, `Trace.artifacts`. Add Mode B `run_oneshot(cmd, timeout, network)` to the sandbox layer.

Day 3–4: build `CodingScenario` + one template + one case end-to-end in `--mock` mode. Get CSV output working.

Day 5–6: add the gates pipeline (install → build → playwright). Bind-mount pnpm store. Test `--live` mode locally with Colima.

Day 7: add `--replay` mode. Generate golden patches by hand for the three cases.

Day 8–9: frontend. Add the `app_preview` render case; reuse `terminal_log` and `code`/`diff` rendering. Render `TodoItem[]` from the existing `plan_updated` stream as a checklist. Verify SSE stream end-to-end.

Day 10: budget enforcement, CSV polish, docs, the CI workflow.

## 6. What This Buys

- A working coding-eval loop you can demo
- A CI signal on every PR (replay mode, no LLM cost)
- A foundation that the long-term doc layers onto, not replaces
- Roughly $5–20 per full `--live` regression run (3 cases × 1 agent), not $100+

## 7. Explicit Non-Goals for MVP

- Production-grade isolation (Docker default + LocalSandbox fallback is fine)
- Multi-tenant safety
- Cross-browser visual regression
- Performance budgets
- Accessibility audits
- Cost/latency dashboards
- Baseline-vs-candidate comparison UI
- Anything to do with users other than the developer running the eval

These are all in the long-term doc and they all matter — just not in week 1.
