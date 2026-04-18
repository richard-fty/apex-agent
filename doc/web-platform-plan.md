# Apex Agent — Web Platform Implementation Plan

> Draft for review. Target: a Manus-style web agent (chat + live artifacts + sandboxed execution) that scales from a single-user local demo to a multi-tenant SaaS.

## 1. Goals

- **Primary UX**: a web UI where the user talks to the agent and watches it work in real time — streaming chat, live file artifacts, running code in a sandbox, plan/todo side panel.
- **Event-driven UI**: every meaningful runtime action emits a typed event the UI can render. No polling.
- **Scalable by design**: the wire protocol (HTTP + SSE) never changes. Internal implementations (event bus, session store, worker model) swap out as load grows.
- **Robust**: no race conditions between turn execution and UI stream. Clean session lifecycle. Graceful reconnection.

## 2. Non-goals (for this plan)

- Mobile clients.
- Full production auth/billing (stubbed for MVP, designed for later).
- Kubernetes manifests (cover deployment only at the shape-of-the-system level).
- Replacing the CLI (`main.py`) — it stays as an in-process script runner.
- Retaining the TUI — it becomes a debug client, optional.

## 3. Current state (honest baseline)

- **No server.** `tui/app.py` and `main.py` both call `SharedTurnRunner` in-process.
- **SQLite archive** (`agent/session/archive.py`) stores events per session.
- **Consumer polls the archive** (`subscribe_events`, 100ms loop) and uses session state as termination signal — fragile; source of recent races.
- **Event vocabulary is thin**: tokens, tool_started, approval_requested, turn_finished. Not enough for an artifact-oriented UI.
- **Artifacts have no first-class model**. File writes happen in the sandbox, but the UI has no way to know "a file was written, here's its content."
- **Sandboxing exists** (`agent/runtime/sandbox.py` with Docker + local backends).

## 4. Target architecture (end state)

```
┌─────────────┐      HTTP/SSE       ┌──────────────────┐
│  React UI   │  ◄──────────────►   │   Edge (FastAPI) │
│  (Vite+TS)  │   EventSource +     │   - Auth         │
│             │   POST actions      │   - SSE handler  │
└─────────────┘                     │   - REST CRUD    │
                                    └───────┬──────────┘
                                            │ enqueue
                                            ▼
                                    ┌──────────────────┐
                                    │  Worker pool     │
                                    │  (Arq / Celery)  │
                                    │  - Turn tasks    │
                                    │  - Sandbox mgmt  │
                                    │  - LLM calls     │
                                    └───────┬──────────┘
                                            │ publish events
                                            ▼
                                    ┌──────────────────┐
                                    │  Event Bus       │
                                    │  (Redis Pub/Sub) │
                                    └──────────────────┘
                                            │
                           ┌────────────────┼────────────────┐
                           ▼                ▼                ▼
                    ┌────────────┐  ┌────────────┐  ┌────────────┐
                    │  Session   │  │  Artifact  │  │   Trace    │
                    │  Store     │  │  Store     │  │   Store    │
                    │ (Postgres) │  │  (S3/FS)   │  │ (Postgres) │
                    └────────────┘  └────────────┘  └────────────┘
```

Phase 1 collapses the right three columns into a single process (SQLite + filesystem + in-memory queue). The API surface stays identical.

## 5. Core abstractions (stable across all phases)

### 5.1 Event schema (`agent/events/schema.py`)

Pydantic discriminated union. Every event has: `seq`, `session_id`, `turn_id`, `timestamp`, `type`, and a type-specific payload. Core types:

| Category | Event type | Purpose |
|---|---|---|
| Lifecycle | `session_created` | Session ready |
| | `turn_started` | New turn beginning |
| | `turn_finished` | Turn ended (with final assistant content) |
| | `stream_end` | Sentinel: SSE consumer should close this stream |
| | `error` | Turn errored |
| Reasoning | `assistant_token` | Streaming text delta |
| | `assistant_message` | Final assistant message |
| | `plan_updated` | Plan/todo list changed |
| Tool calls | `tool_started` | Tool invocation began |
| | `tool_finished` | Tool invocation complete |
| | `tool_denied` | Policy denied a tool |
| | `approval_requested` | Turn paused for user approval |
| | `approval_resolved` | User approved or denied |
| Artifacts | `artifact_created` | New artifact (id, kind, name, initial metadata) |
| | `artifact_patch` | Incremental content. For append-only kinds (markdown, code being written, terminal_log): `{id, text, op: "append"}`. For mutable kinds: `{id, content, op: "replace"}`. Server coalesces small chunks to ~50ms intervals to avoid event flooding. |
| | `artifact_finalized` | Artifact complete (checksum, final size) |
| | `artifact_deleted` | Artifact removed |
| Sandbox | `sandbox_exec_started` | Command started in sandbox |
| | `sandbox_exec_output` | stdout/stderr chunk |
| | `sandbox_exec_finished` | Command complete (exit code) |
| Browser (future) | `browser_navigated` | URL + screenshot ID |
| | `browser_action` | Click/type/etc. |
| Usage | `usage` | Token/cost for a step |

Each event is a subclass of a base `AgentEvent` with `type: Literal[...]` as the discriminator. Pydantic `.model_dump_json()` serializes for SSE; `TypeAdapter(Event).validate_json()` deserializes on client.

### 5.2 Event bus (`agent/events/bus.py`)

```python
class EventBus(Protocol):
    async def publish(self, session_id: str, event: AgentEvent) -> None: ...
    async def subscribe(
        self, session_id: str, *, since_seq: int | None = None
    ) -> AsyncIterator[AgentEvent]: ...
```

Two implementations:
- `InMemoryEventBus`: dict of `session_id → asyncio.Queue`, with replay buffer for reconnect-within-window.
- `RedisEventBus` (Phase 3): Redis Pub/Sub channels keyed by session_id, plus Redis streams for replay.

The runtime depends only on the `EventBus` interface.

### 5.3 Artifact store (`agent/artifacts/store.py`)

```python
class ArtifactStore(Protocol):
    async def create(self, session_id: str, spec: ArtifactSpec) -> Artifact: ...
    async def append(self, artifact_id: str, chunk: bytes) -> None: ...
    async def finalize(self, artifact_id: str) -> Artifact: ...
    async def read(self, artifact_id: str) -> AsyncIterator[bytes]: ...
    async def metadata(self, artifact_id: str) -> Artifact: ...
```

Artifact kinds: `code`, `markdown`, `text`, `json`, `image`, `pdf`, `file`, `terminal_log`, `browser_screenshot`.

Two implementations:
- `FilesystemArtifactStore`: writes to `results/artifacts/{session_id}/{artifact_id}`, JSON metadata sidecar.
- `S3ArtifactStore` (Phase 4): S3-compatible, signed URLs for client reads.

### 5.4 Session store (`agent/session/store.py`)

```python
class SessionStore(Protocol):
    async def create(self, spec: SessionSpec) -> Session: ...
    async def get(self, session_id: str) -> Session | None: ...
    async def update(self, session_id: str, patch: SessionPatch) -> Session: ...
    async def list_events(self, session_id: str, *, since: int = 0) -> list[AgentEvent]: ...
    async def append_event(self, session_id: str, event: AgentEvent) -> None: ...
```

Today: SQLite-backed. Later: Postgres. The schema stays the same.

## 6. Runtime changes

### 6.1 Replace archive polling with event bus + sentinel

Turn execution publishes events to the bus and, as a side-effect, persists them to the session store. The consumer subscribes to the bus (push, not poll) and terminates on `stream_end`. The archive stays as the durable record — for reconnection replay and audit — but is no longer the synchronization channel.

### 6.2 Artifact-aware tools

Tools that produce file-like output (code execution, file writes, search results, reports) create artifacts via the store and emit `artifact_created` / `artifact_patch` events. Concrete tools to update:
- `sandbox_exec` → streams `sandbox_exec_output`; if the command writes files, emits `file_written` + `artifact_created`.
- `write_file` / `edit_file` → creates artifact from the final content.
- `generate_chart` → creates image artifact.
- `research_and_report` → creates markdown artifact.

### 6.3 Plan-as-artifact

The agent's todo list is an artifact of kind `plan`. Updates emit `plan_updated` with the full current plan (small enough that diffs aren't worth it at first).

## 7. Server (`agent/server/`)

FastAPI app. Structure:
- `agent/server/app.py` — app factory, middleware, CORS.
- `agent/server/routes/sessions.py` — session CRUD.
- `agent/server/routes/turns.py` — POST new turn.
- `agent/server/routes/events.py` — SSE stream (`GET /sessions/{id}/events`).
- `agent/server/routes/approvals.py` — POST approval resolution.
- `agent/server/routes/artifacts.py` — GET artifact content (bytes, signed in Phase 4).
- `agent/server/auth.py` — auth: registration, login, logout, session cookie validation.
- `agent/server/routes/auth.py` — `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`.

### 7.0 Auth model (MVP)

- **Storage**: two tables — `users(id, username UNIQUE, password_hash, created_at)` and `auth_sessions(token, user_id, expires_at, created_at)`. Hash via argon2-cffi.
- **Flow**: register → login → HTTP-only SameSite=Lax session cookie (`apex_session`, 30-day expiry, sliding). Logout deletes the `auth_sessions` row.
- **Per-request**: a FastAPI dependency `require_user` reads the cookie, looks up the session row, checks expiry, returns the `User`. Injected into every protected endpoint.
- **Agent session ownership**: `agent_sessions.owner_user_id` FK. All `/sessions/{id}/*` endpoints enforce `agent_session.owner_user_id == current_user.id` or return 404.
- **Rate limiting**: `slowapi` on `/auth/login` — 5 attempts / IP / minute. Returns 429.
- **Security baselines**:
  - Constant-time password verification (argon2-cffi does this).
  - Always hash attempted password even if user not found (prevents user enumeration via timing).
  - Generic error messages on login failures.
  - Password: min 8 chars, no composition rules.
  - HTTPS required in any non-localhost deployment (cookie `Secure` flag).
  - No password emails / "forgot password" in MVP — add with a proper email flow later.

**Out of scope for MVP auth** (explicitly deferred): OAuth/SSO, email verification, password reset flows, MFA, admin roles, API keys. All layer on top of this base without breaking the contract.

### 7.1 SSE endpoint spec

```
GET /sessions/{id}/events
Headers:
  Last-Event-ID: <seq>  (optional; for reconnection replay)
  Authorization: Bearer <token>
Response:
  Content-Type: text/event-stream
  Each event: `id: <seq>\nevent: <type>\ndata: <json>\n\n`
  Closes on `stream_end` event or client disconnect.
```

### 7.2 Turn lifecycle over HTTP

1. Client: `POST /sessions` → `{session_id}`.
2. Client opens `GET /sessions/{id}/events` (SSE).
3. Client: `POST /sessions/{id}/turns { "user_input": "..." }` → `202`.
4. Server: publishes events to bus, which flow through SSE to client.
5. If `approval_requested` event arrives, client: `POST /sessions/{id}/approvals { "action": "approve_once" }`.
6. Server resumes turn, publishes more events.
7. Client sees `turn_finished` followed by `stream_end`. Idle until next turn.
8. Same SSE stream stays open across turns (or client reconnects with `Last-Event-ID`).

### 7.3 Reconnection

On SSE disconnect, the React client reconnects with `Last-Event-ID: <last_seq_seen>`. The server replays events `> last_seq` from the session store before attaching to the live bus. No client-side deduplication needed.

## 8. React client (`web/`)

Separate directory, its own `package.json`. Stack:
- **Vite + TypeScript + React 18**
- **Tailwind CSS** for styling
- **Zustand** for local state (session, events, artifacts)
- **@microsoft/fetch-event-source** (or native EventSource) for SSE
- **Monaco** for code artifact rendering
- **react-markdown** for markdown artifacts
- **xterm.js** for terminal artifacts
- **react-router** (simple; session list + single session view)

### 8.1 Layout — Claude.ai-style split panel

Two modes:

**Collapsed mode** (no artifact yet, or user collapsed the panel): chat takes full width.

```
┌─────────────────────────────────────────────────┐
│  Top bar: session name, model, status, /logout  │
├─────────────────────────────────────────────────┤
│                                                 │
│   Chat pane (full width)                        │
│   - user message                                │
│   - thinking indicator                          │
│   - assistant streaming message                 │
│   - [📄 report.md ]  ← artifact card in chat    │
│                                                 │
│  ─── Plan sidebar (collapsible drawer) ───      │
├─────────────────────────────────────────────────┤
│  Composer: input + attach + approve controls   │
└─────────────────────────────────────────────────┘
```

**Split mode** (artifact open): chat shifts left, artifact panel slides in on the right.

```
┌───────────────────────────────────────────────────────────────┐
│  Top bar                                                       │
├──────────────────────────┬────────────────────────────────────┤
│                          │  Artifact panel  [⤡] [×]           │
│   Chat pane              │  ┌──── dropdown: report.md v2 ──┐  │
│   - user message         │  │ report.md  | script.py | …   │  │
│   - tool_started …       │  └──────────────────────────────┘  │
│   - [📄 report.md] ← hi- │  ┌─── tabs: preview | source ──┐   │
│     lighted (open)       │  │                              │   │
│                          │  │  # Latest News on US–Iran    │   │
│                          │  │                              │   │
│   - assistant streaming  │  │  In the past month, the …    │   │
│     text continues       │  │  ▌ ← live cursor while      │   │
│                          │  │    streaming                 │   │
│                          │  │                              │   │
│                          │  └──────────────────────────────┘   │
├──────────────────────────┴────────────────────────────────────┤
│  Composer                                                       │
└───────────────────────────────────────────────────────────────┘
```

- **Open trigger**: when an `artifact_created` event arrives, the panel auto-opens to that artifact. Clicking an artifact card in chat also opens it.
- **Dropdown** at the top of the panel lists all artifacts in this session (latest first). Switching is instant — state is cached per artifact.
- **Tabs within the panel**: `Preview` (rendered) and `Source` (raw). Default depends on kind: markdown/image/pdf default to Preview; code/json/text default to Source.
- **Header actions**: `[⤡]` toggles full-screen artifact (chat hidden), `[×]` closes the panel (chat expands back). Keyboard: `Ctrl+\` toggles panel, `Ctrl+Shift+F` full-screen.
- **Resize**: vertical drag handle between chat and artifact — min 320px chat, min 400px artifact.
- **Plan sidebar** becomes a left drawer (collapsible button in top-bar) instead of a persistent column, so it doesn't fight for space in split mode.

### 8.2 Live streaming render

The artifact panel re-renders on every `artifact_patch` event. Per kind:

| Kind | Renderer | Streaming strategy |
|---|---|---|
| `markdown` | `react-markdown` + `remark-gfm` | Accumulate raw text; re-render on each patch. Use a "healing" wrapper that auto-closes unclosed code fences/lists so partial markdown doesn't look broken. Syntax-highlight via `rehype-highlight`. |
| `code` | Monaco editor (read-only) | `editor.setValue(content)` on each patch. Disable all user edit actions; show a live "streaming" badge in the header. |
| `terminal_log` | `xterm.js` | Append the new chunk via `term.write(chunk)` (xterm handles ANSI natively). |
| `image` | `<img>` with progressive URL | Only final content streams are meaningful — wait for `artifact_finalized`, then set src. Show a spinner until then. |
| `pdf` | `react-pdf` | Same as image — render only after finalize. |
| `json` | Monaco (json mode) with fold | Re-parse + tree-render on patch; fall back to raw view if JSON is not yet valid. |
| `plan` | Custom checklist component | Render from `plan_updated` payload directly. |

**Render throttling**: `artifact_patch` events can arrive faster than the browser can render. The client coalesces patches for the same artifact using `requestAnimationFrame` — at most one render per animation frame (~16ms). The server side also coalesces: the runtime buffers small artifact chunks and emits `artifact_patch` at ~50ms intervals or on chunk boundaries.

**Auto-scroll in artifact panel**: follow-latest (pin to bottom) while streaming, UNLESS the user has scrolled up — then freeze, show a "Jump to latest" floating button.

**Cursor/progress indicator**: while an artifact is still streaming, the panel shows a blinking cursor at the end of the content and a subtle header badge ("Streaming…"). Both disappear on `artifact_finalized`.

### 8.3 Artifact card inline in chat

When an artifact appears mid-conversation, render a compact card in the chat flow:

```
┌──────────────────────────┐
│ 📄 report.md              │  ← icon by kind
│ Latest News on US–Iran…  │  ← first line / description
│ 2.3 KB · streaming…       │  ← size + status
└──────────────────────────┘
    click → opens panel
```

Clicking it opens/switches the artifact panel to that artifact. The current artifact shown in the panel is highlighted in chat so the user can see the correlation.

### 8.4 State shape (Zustand)

```ts
{
  // Server-sourced (event-derived)
  session: { id, model, status },
  events: AgentEvent[],          // append-only log
  messages: Message[],           // derived: chat bubbles
  artifacts: Map<id, Artifact>,  // derived from artifact_* events
  plan: PlanStep[],              // derived from plan_updated
  pending: ApprovalRequest | null,
  usage: { tokens, cost },

  // Client-only UI state
  ui: {
    panelOpen: boolean,
    panelFullscreen: boolean,
    activeArtifactId: string | null,
    artifactView: 'preview' | 'source',  // per-kind default, persisted
    planDrawerOpen: boolean,
    followLatest: Map<artifactId, boolean>,  // auto-scroll per artifact
  }
}
```

UI state is separate from event-derived state so replaying events is idempotent and doesn't stomp on user choices (e.g., don't flip `artifactView` back to preview just because a patch arrived).

Derivations happen in selectors; the event log is the source of truth, matching the server.

### 8.5 Event → UI mapping

A single reducer-like function takes `(state, event)` and returns the next state. This mirrors the event schema 1:1 and makes the UI trivially testable — feed it a recorded event trace, snapshot the derived state.

## 9. Scaling phases

| Phase | What's new | What's swapped |
|---|---|---|
| **0 — MVP local** | FastAPI + SSE; React app; in-memory bus; filesystem artifacts; SQLite sessions. One process. | — |
| **1 — Auth & multi-user** | JWT auth, per-user session ownership, Postgres. | SQLite → Postgres. |
| **2 — Horizontal edge** | N FastAPI pods behind LB with sticky SSE. | — (infra only). |
| **3 — Workers + broker** | Turn execution moves to Arq worker pool; Redis Pub/Sub event bus. Edge pods just serve SSE and auth. | InMemoryEventBus → RedisEventBus; inline turn → enqueued job. |
| **4 — Object storage** | Artifacts on S3 with signed URLs. | FilesystemArtifactStore → S3ArtifactStore. |
| **5 — Isolation hardening** | Firecracker/gVisor sandboxes, per-tenant sandbox pools. | DockerSandbox → FirecrackerSandbox. |

At every phase, the React client and HTTP/SSE API are unchanged.

## 10. Milestones & commit plan

### Milestone M1 — Contracts (1–2 days)
- `agent/events/schema.py`: event types + pydantic discriminated union
- `agent/events/bus.py`: `EventBus` protocol + `InMemoryEventBus`
- `agent/artifacts/model.py` + `agent/artifacts/store.py`: `ArtifactStore` protocol + `FilesystemArtifactStore`
- `agent/session/store.py`: `SessionStore` protocol + SQLite impl wrapping today's archive
- Tests for each contract

One PR, no behavior change to existing code yet.

### Milestone M2 — Runtime integration (2–3 days)
- Rework `ManagedAgentRuntime` to publish `AgentEvent`s to `EventBus` (not raw dicts to archive)
- Add `stream_end` sentinel emission at turn/terminal transitions
- `SharedTurnRunner` consumes from `EventBus`, not archive polling
- Retrofit TUI to use the new bus (still in-process)
- Remove `SessionEventStream` / `subscribe_events` polling path
- Tests: runtime emits expected event sequences

Delete `agent/session/archive.py::subscribe_events`. This is the commit where the races stop existing structurally.

### Milestone M3 — Artifact instrumentation (2 days)
- Wire `artifact_*` events into:
  - Sandbox exec tool (terminal_log artifact + file_written events)
  - `write_file`, `edit_file`
  - Chart/report tools
- Plan artifact (kind=`plan`, `plan_updated` event on todo changes)
- Tests

### Milestone M4 — FastAPI server + auth (5–6 days)
- `agent/server/app.py` + routes
- **Auth**: users + auth_sessions tables, argon2 hashing, register/login/logout endpoints, `require_user` dependency, rate-limited login
- **Session ownership**: `owner_user_id` FK, enforced on every agent session route (404 on mismatch)
- SSE endpoint with `Last-Event-ID` replay, gated by `require_user`
- Health/readiness endpoints
- `make serve` target
- Integration tests: auth flow, ownership enforcement, SSE happy path

### Milestone M5 — React MVP (6–8 days)
- `web/` project with Vite + TS + Tailwind + Zustand
- **Auth UI**: register page, login page, logged-in shell; auth-required route guard; logout
- SSE hook with reconnection
- Chat pane + Claude-style artifact panel (collapsed/split modes, streaming render, dropdown/tabs)
- Plan sidebar (drawer)
- Artifact viewers: code (Monaco), markdown (react-markdown + healing), terminal (xterm.js), image, pdf, plan
- Approval modal
- Session list + new-session UI
- `make web` (dev server) + `make web-build`
- Smoke tests: register → login → new session → artifact renders live → approval flow → logout

### Milestone M6 — Polish & parity (2–3 days)
- Session list/resume UI
- Cost display
- Error states
- Keyboard shortcuts
- Basic theming

After M6, you have Phase 0 (MVP). Phases 1–5 follow as load/requirements demand.

## 11. Decisions (all resolved for MVP)

| # | Decision | Resolution |
|---|---|---|
| 1 | Web framework | **FastAPI** |
| 2 | React state | **Zustand** |
| 3 | Styling | **Tailwind CSS + shadcn/ui** |
| 4 | Repo layout | **`web/` in-tree** (same repo) |
| 5 | Auth | **Username + password, argon2 hashing, server-side cookie sessions.** Registration or login required to use the agent. No email, OAuth, MFA, or password-reset in MVP. |
| 6 | Session model | **One conversation thread per session**, many turns |
| 7 | Multi-device session resume | **Deferred** to post-MVP (requires Postgres) |
| 8 | Artifact versioning | **Latest-only** for MVP |
| 9 | TUI | **Kept as debug client**; no further investment |
| 10 | LLM provider strategy | **LiteLLM** (multi-provider, already in place) |
| 11 | Artifact panel width | **45% chat / 55% artifact** default; persisted on user drag |
| 12 | Inline-vs-artifact threshold | **>600 chars or tool-produced** becomes artifact; agent can force with `as_artifact: true` hint |
| A | Dev auth bypass | **`APEX_DEV_BYPASS_AUTH=1`** env var auto-logs-in as dev user; off by default, never honored when `ENV=production` |
| B | Session sharing | **Private per-user**; no share links in MVP |

## 12. Risks & how to de-risk

| Risk | Mitigation |
|---|---|
| Event schema churn breaks client | Freeze core events in M1; additive-only after. Version the schema (`v: 1`). |
| SSE disconnect flakiness on mobile networks | Client reconnection with `Last-Event-ID`; server-side 5-min replay buffer. |
| Worker-edge split (Phase 3) is painful | Write runtime to depend only on `EventBus` from day one; swap impls, no call-site changes. |
| React app becomes monolithic | Feature-slice structure: `web/src/features/{chat,artifacts,plan,approval}/`. |
| Sandbox isolation gaps in multi-tenant | Don't ship multi-tenant until Phase 5 (Firecracker/gVisor). Single-tenant or trusted users until then. |
| Cost overruns from runaway agents | Per-turn budget + hard max-steps + per-user daily quota from M1. |

## 13. What I need from you to start

A 🟢 or adjustments on:
- The open decisions in §11
- Whether to fold M1–M2 into one commit (they're tightly coupled) or keep separate
- Which scaling phases are real goals vs. "nice to have" — changes how much abstraction we bake into M1

Once you sign off on this, I'll open M1 as a PR and we'll go.
