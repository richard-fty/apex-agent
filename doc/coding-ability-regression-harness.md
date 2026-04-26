# Coding Ability and Regression Harness Plan

## 1. Purpose

Build a harness that measures whether the agent can turn a user request into a working shipped app, not just a plausible patch or final message.

The harness should support long-horizon coding tasks where the agent:

1. Receives a product or coding task.
2. Chooses or receives a lightweight tech stack.
3. Writes and edits code in an isolated sandbox.
4. Installs dependencies, builds the app, and starts a preview server.
5. Renders the result in a browser artifact.
6. Runs deterministic and judge-based regression checks.
7. Stores the code diff, logs, screenshots, traces, scores, and final preview URL.

This becomes the main regression suite for coding ability.

## 2. Design Principles

- **Test the shipped behavior.** A coding eval passes only when the app builds, boots, renders, and satisfies user-visible checks.
- **Prefer lightweight stacks.** Use the smallest stack that can satisfy the task so evals are cheap, fast, and reproducible.
- **Keep execution hermetic.** Every task execution gets a clean workspace, pinned runtime image, limited network access, bounded resources, and no host secrets.
- **Make artifacts first-class.** Code, logs, screenshots, Playwright traces, videos, patches, and preview URLs are durable outputs, not side effects.
- **Separate deterministic gates from subjective judging.** Build/test/browser checks run first. LLM or human judging only handles product quality and ambiguous success criteria.
- **Compare against baselines.** A candidate agent version is judged relative to the current production/baseline agent on the same frozen tasks.

## 3. MVP Product Model

For the first version, keep the user-facing model simple:

```text
Session
  -> Task
    -> TodoItem
    -> Event
    -> Artifact
```

Definitions:

| Name | Meaning | Example |
|---|---|---|
| Session | A durable user conversation or workspace | One chat thread with the agent |
| Task | One user goal inside the session | "Create a todo app" |
| TodoItem | A decomposed checklist item under the task | "Build todo list UI" |
| Event | One append-only record of what happened | `command_finished`, `todo_updated` |
| Artifact | A durable output produced by the task | Preview URL, screenshot, patch, log |

Do not add a separate `Run` table in the MVP unless the implementation needs it. The `Task` can be the execution boundary. Later, if one task needs multiple retries, multiple candidate agents, or separately isolated stages, introduce:

```text
Session
  -> Task
    -> Attempt
      -> Run
        -> Event
```

For MVP, use `task_id` to group agent messages, todo updates, sandbox commands, browser checks, and artifacts.

### 3.1 Task and Todo Example

User says:

```text
Create a todo app.
```

The system creates:

```text
Session: sess_123
Task: task_001 "Create a todo app"
TodoItems:
  1. Scaffold Vite React app
  2. Build todo list UI
  3. Add create, complete, and delete behavior
  4. Persist todos to localStorage
  5. Build the app
  6. Start preview
  7. Run browser checks
```

Events describe progress:

```text
task_created
todo_list_updated
todo_updated
agent_message
file_changed
command_started
command_output
command_finished
artifact_created
preview_started
browser_screenshot
playwright_finished
task_finished
```

### 3.2 Minimum Tables

```sql
sessions (
  session_id text primary key,
  created_at timestamptz not null,
  updated_at timestamptz not null
);

tasks (
  task_id text primary key,
  session_id text not null,
  title text not null,
  status text not null,
  created_at timestamptz not null,
  updated_at timestamptz not null
);

todo_items (
  todo_id text primary key,
  task_id text not null,
  title text not null,
  status text not null,
  position integer not null,
  created_at timestamptz not null,
  updated_at timestamptz not null
);

events (
  event_id text primary key,
  session_id text not null,
  task_id text not null,
  todo_id text,
  seq integer not null,
  type text not null,
  payload jsonb not null,
  created_at timestamptz not null
);

artifacts (
  artifact_id text primary key,
  session_id text not null,
  task_id text not null,
  kind text not null,
  title text not null,
  uri text not null,
  metadata jsonb not null,
  created_at timestamptz not null
);
```

Use both `event_id` and `seq`:

- `event_id` is the unique primary key for one event.
- `seq` is the monotonically increasing order inside a session, used for replay and SSE reconnects.

### 3.3 Todo Event Contract

When the agent creates or revises the plan:

```json
{
  "type": "todo_list_updated",
  "session_id": "sess_123",
  "task_id": "task_001",
  "seq": 8,
  "payload": {
    "todos": [
      { "id": "todo_1", "title": "Scaffold Vite React app", "status": "completed" },
      { "id": "todo_2", "title": "Build todo list UI", "status": "in_progress" },
      { "id": "todo_3", "title": "Run browser checks", "status": "pending" }
    ]
  }
}
```

When one item changes:

```json
{
  "type": "todo_updated",
  "session_id": "sess_123",
  "task_id": "task_001",
  "todo_id": "todo_2",
  "seq": 17,
  "payload": {
    "status": "completed"
  }
}
```

Valid todo statuses:

```text
pending
in_progress
completed
failed
skipped
```

## 4. Default Tech Stack Policy

The agent should not freely pick a heavy framework for every task. The harness should provide a small set of blessed templates and route tasks to them.

| Task type | Default stack | Reason |
|---|---|---|
| Frontend app, dashboard, tool, game, landing page | Vite + React + TypeScript | Fast install/build, static output, simple preview, low memory |
| Static/content-heavy site | Astro | Lightweight static output with optional islands |
| Full-stack app with real API/auth/database requirements | Next.js + TypeScript | Server routes, SSR, auth/session/database patterns |
| Backend-heavy task | Small API service + Vite frontend | Keeps frontend preview light while testing backend behavior |
| Very small UI prototype | Static HTML/CSS/JS | Minimum dependency and fastest preview |

Default rule:

```text
If frontend-only is enough, use Vite + React.
Use Next.js only when the prompt requires server-side behavior, API routes, auth, database integration, SSR, uploads, or production full-stack structure.
```

## 5. End-To-End Harness Flow

```text
User task or eval case
  -> create clean sandbox workspace
  -> unpack repo/template/task fixture
  -> start agent with coding tools
  -> agent emits todo list
  -> agent edits files
  -> build gate
  -> runtime gate
  -> browser gate
  -> app preview artifact
  -> visual/product judge
  -> scoring and regression comparison
  -> artifact archival
```

Each eval task should produce one immutable execution record. In MVP this can be keyed by `task_id`; later it can be split into `attempt_id` and `run_id`.

```json
{
  "task_id": "task_20260426_001",
  "case_id": "frontend_kanban_drag_drop_001",
  "agent_version": "candidate",
  "stack": "vite-react",
  "status": "completed",
  "build_passed": true,
  "app_booted": true,
  "browser_checks_passed": true,
  "visual_score": 0.97,
  "judge_score": 4,
  "duration_sec": 320,
  "cost_usd": 0.41,
  "artifacts": {
    "patch": "artifacts/task_20260426_001/patch.diff",
    "stdout": "artifacts/task_20260426_001/stdout.log",
    "stderr": "artifacts/task_20260426_001/stderr.log",
    "screenshots": "artifacts/task_20260426_001/screenshots/",
    "playwright_trace": "artifacts/task_20260426_001/trace.zip",
    "preview_url": "https://task-20260426-001.preview.example.com"
  }
}
```

## 6. Code Shipping

Code should be shipped into the sandbox as a content-addressed bundle plus an execution manifest.

### 6.1 Bundle Shape

```text
bundle.tar.zst
  package.json
  pnpm-lock.yaml
  index.html
  src/
  public/
  tests/
  eval/
    playwright.spec.ts
    rubric.md
```

For template-based tasks, the bundle contains:

- A frozen starter repo.
- The user prompt.
- Optional seed data.
- Optional expected screenshots or golden files.
- Optional hidden tests.

### 6.2 Execution Manifest

```json
{
  "case_id": "frontend_dashboard_001",
  "task_id": "task_001",
  "stack": "vite-react",
  "workdir": "/workspace",
  "package_manager": "pnpm",
  "install": ["pnpm", "install", "--frozen-lockfile"],
  "build": ["pnpm", "build"],
  "serve": [
    "pnpm",
    "exec",
    "vite",
    "preview",
    "--host",
    "0.0.0.0",
    "--port",
    "3000",
    "--strictPort"
  ],
  "health_url": "http://127.0.0.1:3000",
  "browser_tests": ["pnpm", "exec", "playwright", "test"],
  "resource_limits": {
    "timeout_sec": 600,
    "memory_mb": 2048,
    "cpu": 2,
    "max_processes": 128,
    "max_stdout_mb": 20
  },
  "network_policy": {
    "install": true,
    "runtime": false
  }
}
```

The manifest makes execution explicit and prevents the harness from guessing how to run arbitrary projects.

## 7. Sandbox Execution

Use containerized execution as the default. Bubblewrap can be added later as an optimization, but Docker/OCI gives better reproducibility for Node, browsers, and full-stack apps.

### 7.1 Local Development With Colima

On macOS, the local Docker CLI can use Colima as the Linux VM and container daemon.

```text
docker CLI
  -> Docker context: colima
  -> Colima Linux VM
  -> sandbox container
  -> /workspace mounted from a temporary task directory
```

Start Colima before running sandbox tasks:

```bash
colima start --cpu 4 --memory 8 --disk 60
docker version
docker run hello-world
```

For this repo, Postgres may also run through Docker/Colima via `docker compose`. Keep backend infrastructure containers and code-execution sandbox containers logically separate:

```text
agent backend services:
  can access Postgres, Redis, artifact store

code execution sandbox:
  should not access Postgres, Redis, host secrets, Docker socket, or internal APIs by default
```

The sandbox should mount a temporary task workspace, not the whole developer repo:

```text
host repo or fixture bundle
  -> /tmp/apex-runs/task_001/workspace
  -> docker run -v /tmp/apex-runs/task_001/workspace:/workspace
```

### 7.2 MVP Runtime

```text
Docker or OCI container per task execution
  - pinned Node image
  - pinned package manager
  - pinned Playwright browser image
  - clean workspace mount
  - resource limits
  - no host home directory
  - no host secrets
```

Example Vite build container:

```bash
docker run --rm \
  --name apex-task-build \
  --cpus=2 \
  --memory=2g \
  --pids-limit=128 \
  --network none \
  -v /tmp/apex-runs/task_001/workspace:/workspace:rw \
  -w /workspace \
  node:22-bookworm \
  bash -lc "corepack enable && pnpm build"
```

When dependency installation needs network, allow network only for the install stage. Disable it for build/test/runtime unless the eval explicitly requires network.

### 7.3 Production Runtime

For untrusted user code, strengthen isolation:

```text
OCI container
  + gVisor, Kata, Firecracker, or another microVM/container sandbox layer
  + cgroups for CPU/memory/process limits
  + read-only base filesystem
  + writable workspace and tmpfs only
  + network disabled after dependency installation
```

### 7.4 Execution Stages

```text
prepare_workspace
  -> unpack source bundle
  -> apply fixture metadata
  -> initialize git repo for diff capture

agent_run
  -> expose allowed tools
  -> let agent edit files and run commands
  -> stream events and terminal logs

install_gate
  -> run manifest.install
  -> cache dependencies by lockfile hash where safe

build_gate
  -> run typecheck/lint/build
  -> fail hard on compile errors

runtime_gate
  -> start server from manifest.serve
  -> wait for health_url
  -> capture server logs

browser_gate
  -> run Playwright checks
  -> capture screenshots, traces, console errors, network failures

finalize
  -> capture patch
  -> archive artifacts
  -> destroy sandbox
```

## 8. Agent UI: Todo Items and Artifacts

The agent UI should render task state from events. The agent/runtime emits append-only events; the frontend reduces those events into current UI state.

### 8.1 Event-Driven Todo UI

Suggested layout:

```text
+-------------------------+----------------------------+
| Chat / Agent Activity   | Artifact Side Panel        |
|                         |                            |
| User: create a todo app | Live app preview iframe    |
| Agent messages          | Screenshots, logs, patch   |
|                         |                            |
| Todo checklist          |                            |
| [x] Scaffold app        |                            |
| [x] Build UI            |                            |
| [ ] Run browser checks  |                            |
+-------------------------+----------------------------+
```

Frontend reducer shape:

```ts
type TodoStatus = "pending" | "in_progress" | "completed" | "failed" | "skipped";

type TodoItem = {
  id: string;
  title: string;
  status: TodoStatus;
};

type TaskState = {
  taskId: string;
  todos: TodoItem[];
  artifacts: Artifact[];
  selectedArtifactId: string | null;
};

function applyEvent(state: TaskState, event: AgentEvent): TaskState {
  switch (event.type) {
    case "todo_list_updated":
      return { ...state, todos: event.payload.todos };

    case "todo_updated":
      return {
        ...state,
        todos: state.todos.map((todo) =>
          todo.id === event.todo_id ? { ...todo, ...event.payload } : todo
        ),
      };

    case "artifact_created":
      return {
        ...state,
        artifacts: [...state.artifacts, event.payload.artifact],
        selectedArtifactId: event.payload.artifact.id,
      };

    default:
      return state;
  }
}
```

The UI crosses off a checklist item when it receives:

```json
{
  "type": "todo_updated",
  "todo_id": "todo_2",
  "payload": {
    "status": "completed"
  }
}
```

### 8.2 Artifact Side Panel

The artifact side panel renders by artifact kind:

| Artifact kind | UI treatment |
|---|---|
| `app_preview` | iframe pointing to isolated preview URL |
| `browser_screenshot` | image preview |
| `terminal_log` | streaming log viewer |
| `patch` | diff viewer |
| `source_file` | code viewer |
| `playwright_trace` | download/open trace link |

Example app preview event:

```json
{
  "type": "artifact_created",
  "session_id": "sess_123",
  "task_id": "task_001",
  "seq": 42,
  "payload": {
    "artifact": {
      "id": "artifact_preview_1",
      "kind": "app_preview",
      "title": "Todo App Preview",
      "url": "https://task-001.preview.example.com",
      "status": "ready"
    }
  }
}
```

Example React rendering:

```tsx
function ArtifactPanel({ artifact }: { artifact: Artifact | null }) {
  if (!artifact) return null;

  if (artifact.kind === "app_preview") {
    return (
      <iframe
        src={artifact.url}
        title={artifact.title}
        sandbox="allow-scripts allow-forms allow-same-origin"
        className="artifact-preview-frame"
      />
    );
  }

  if (artifact.kind === "browser_screenshot") {
    return <img src={artifact.url} alt={artifact.title} />;
  }

  if (artifact.kind === "terminal_log") {
    return <pre>{artifact.content}</pre>;
  }

  return null;
}
```

## 9. Artifact Preview

The preview should be treated as a sandboxed artifact, not as part of the main product origin.

### 9.1 Preview URL

Use a unique origin per task execution:

```text
https://task-<task_id>.preview.example.com
```

This prevents the app under test from sharing cookies, storage, or origin permissions with the main Apex UI.

### 9.2 Preview Proxy

```text
Browser/UI
  -> preview proxy
  -> sandbox app server on internal network
```

The proxy should enforce:

- Task-execution TTL.
- Allowed ports only.
- Request and response size limits.
- No access to metadata endpoints.
- No access to internal services except the app preview server.
- Optional auth token tied to the user/session.

### 9.3 UI Artifacts

The product UI should show:

- Live terminal output.
- File tree and changed files.
- Build status.
- Browser preview.
- Screenshots.
- Playwright trace/video.
- Final patch.
- Eval score summary.

For embedded previews, use an iframe on a separate origin. Avoid sharing main-app auth cookies with the preview.

## 10. Regression Test Design

Regression tests should measure coding ability at three levels.

### 10.1 Level 1: Deterministic Engineering Gates

These are hard gates:

- Dependency install succeeds.
- Typecheck succeeds.
- Lint succeeds, if configured.
- Unit tests pass.
- Production build succeeds.
- App server starts.
- Browser can load the app.
- No uncaught runtime error on first page load.
- No forbidden file access or secret leakage.

Example Vite case:

```bash
pnpm install --frozen-lockfile
pnpm build
pnpm exec vite preview --host 0.0.0.0 --port 3000 --strictPort
pnpm exec playwright test
```

### 10.2 Level 2: Browser Behavior Gates

Playwright should verify actual user workflows:

```ts
import { test, expect } from "@playwright/test";

test("user can add a task", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("textbox", { name: "Task name" }).fill("Write eval plan");
  await page.getByRole("button", { name: "Add" }).click();
  await expect(page.getByText("Write eval plan")).toBeVisible();
  await expect(page).toHaveScreenshot("task-added.png");
});
```

Track:

- DOM assertions.
- Interaction success.
- Console errors.
- Failed network requests.
- Screenshot diffs.
- Accessibility violations, if an axe check is enabled.
- Performance budget for app load, if relevant.

### 10.3 Level 3: Product Quality Judge

Use LLM or human judging only after deterministic gates pass.

Judge dimensions:

- Did the app satisfy the user request?
- Is the UX complete enough for the requested workflow?
- Are visible states handled: empty, loading, error, success?
- Is the implementation scoped and maintainable?
- Did the agent avoid unrelated changes?
- Is the final answer accurate about what was built?

Rubric:

```text
5 = fully satisfies the task; builds, renders, interactions work, polished enough
4 = satisfies core task; minor quality gaps
3 = partial completion; useful but incomplete
2 = runs but misses major requirements
1 = does not build, boot, or solve the task
```

## 11. Eval Case Format

```json
{
  "id": "vite_todo_drag_drop_001",
  "title": "Add drag-and-drop to a todo board",
  "difficulty": "medium",
  "stack": "vite-react",
  "repo_bundle": "s3://eval-fixtures/vite_todo_base.tar.zst",
  "prompt": "Add drag-and-drop between Todo, Doing, and Done columns.",
  "allowed_files": ["src/**", "package.json", "pnpm-lock.yaml"],
  "disallowed_files": [".env", "eval/hidden/**"],
  "success_criteria": [
    "user can drag a card between columns",
    "state persists after page refresh",
    "app has no console errors",
    "production build passes"
  ],
  "commands": {
    "install": ["pnpm", "install", "--frozen-lockfile"],
    "build": ["pnpm", "build"],
    "serve": ["pnpm", "exec", "vite", "preview", "--host", "0.0.0.0", "--port", "3000"],
    "test": ["pnpm", "exec", "playwright", "test"]
  },
  "scoring": {
    "build": 0.2,
    "browser_tests": 0.4,
    "visual": 0.2,
    "judge": 0.2
  }
}
```

## 12. Regression Comparison

Every release candidate should run against the same frozen suite as the baseline agent.

```text
baseline agent + eval case -> score A
candidate agent + eval case -> score B
compare B against A
```

Release blockers:

- Any hard gate failure in a previously passing critical case.
- Severe sandbox violation.
- App build/boot regression above threshold.
- More than N previously passing cases now failing.
- Candidate score drops more than configured tolerance.
- Candidate has worse cost/latency above budget without quality improvement.

Suggested initial thresholds:

```text
Critical cases: 100% pass required
Core coding suite: no more than 2% absolute pass-rate drop
Severe failures: 0 allowed
Average judge score: no more than 0.2 drop
Cost: no more than 20% increase unless pass rate improves
Latency: no more than 25% increase unless pass rate improves
```

## 13. Eval Suite Tiers

### Tier C1: Basic Coding

- Fix a compile error.
- Add a small component.
- Wire a button to state.
- Fix a failing unit test.
- Make a static page responsive.

### Tier C2: Browser-Visible Product Work

- Build a dashboard from mock data.
- Add filtering/sorting/search.
- Implement form validation.
- Add drag-and-drop or multi-step interaction.
- Persist UI state to local storage.

### Tier C3: Full-Stack Work

- Add API route.
- Connect UI to backend.
- Implement CRUD flow.
- Add auth-like session mock.
- Add file upload or server-side validation.

### Tier C4: Long-Horizon App Build

- Build a complete small app from a product prompt.
- Recover from failing install/build.
- Iterate after browser preview reveals UI bugs.
- Preserve original goal across many steps.
- Produce useful final artifacts and explanation.

## 14. Observability and Stored Artifacts

Store these for every task execution:

- Input prompt and case manifest.
- Agent version and runtime config.
- Tool-call event log.
- File patch.
- Final workspace checksum.
- Dependency install log.
- Build log.
- Server log.
- Browser console log.
- Network failures.
- Screenshots.
- Playwright trace/video.
- Judge rubric and score.
- Cost, token, latency, step count.
- Sandbox policy decisions.

These artifacts make failures debuggable and let humans inspect why one agent version regressed.

## 15. MVP Implementation Plan

### Phase 1: Local Harness

- Create two templates: `vite-react` and `next-fullstack`.
- Define the session, task, todo item, event, artifact, and execution manifest schemas.
- Implement sandbox worker around Docker/OCI, with Colima as the local macOS runtime.
- Add build/runtime/browser gates.
- Save artifacts to local filesystem.
- Run a small suite of 10 eval cases.

### Phase 2: Preview Artifacts

- Add preview proxy with unique task execution URLs.
- Stream terminal/build/browser events into the UI.
- Add todo checklist rendering from `todo_list_updated` and `todo_updated` events.
- Add artifact panel for app preview, screenshots, traces, patch, and logs.
- Add iframe preview from isolated preview origin.

### Phase 3: Regression Dashboard

- Store task execution results in Postgres or SQLite.
- Compare baseline vs candidate agent versions.
- Show pass rate, severe failures, score deltas, cost, and latency.
- Add release-blocking thresholds.

### Phase 4: Hardened Production Sandbox

- Move untrusted execution to gVisor, Kata, Firecracker, or equivalent.
- Add stricter network egress policy.
- Add dependency cache keyed by lockfile hash.
- Add per-task TTL cleanup and quota enforcement.
- Add secret scanning and forbidden path checks.

## 16. Open Decisions

- Whether the first preview proxy should be local-only or production-hosted.
- Whether dependency installation can use network by default or must use a curated package cache.
- Whether visual baselines are stored per case, per browser, and per viewport.
- Whether LLM judging should run synchronously in CI or asynchronously after deterministic gates.
- Which cases are critical release blockers versus score-only cases.
- Whether to keep `Task` as the only execution boundary or introduce `Run` after MVP.

## 17. Recommended Starting Point

Start with:

```text
Session -> Task -> TodoItem -> Event -> Artifact
Vite + React + TypeScript for frontend tasks
Next.js only for full-stack tasks
Docker/OCI sandbox per task execution
Colima + Docker CLI for local macOS execution
Playwright for browser checks
Filesystem artifact store for MVP
Unique preview URL per task execution
Baseline-vs-candidate regression comparison
```

This gives the fastest useful loop: the agent writes code, the sandbox builds and serves it, the browser proves it works, and the eval suite catches regressions in coding ability.
