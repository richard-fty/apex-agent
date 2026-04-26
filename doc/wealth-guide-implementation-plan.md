# Wealth Guide — Implementation Plan

> Companion to [financial-coach-design-principles.md](financial-coach-design-principles.md) (principles) and [mass-affluent-wealth-guide-thesis.md](mass-affluent-wealth-guide-thesis.md) (product thesis).
>
> **Purpose:** concrete implementation details for the MVP. Routes, schemas, components, milestones. This doc drifts as we build; the principles doc does not.

## 1. Scope recap

Ship the Financial Coach MVP as a product layer on top of the existing Apex Agent stack. Stack is locked:

| Layer | Tech | Location |
|---|---|---|
| Frontend | Vite + React + TypeScript + Tailwind + Zustand | `frontend/` |
| Backend | FastAPI + SSE | `backend/apex_server/` |
| Database | **Plain Postgres 16** (via `asyncpg`) | hosted (Neon / Railway / Fly / RDS) |
| Agent core | Apex Agent skill packs, sessions, artifacts | `core/` |
| Artifacts | Filesystem for MVP, S3 later | `backend/results/artifacts/` |

Principles come from [financial-coach-design-principles.md](financial-coach-design-principles.md). This doc does not restate them.

## 2. Architecture snapshot

```
┌──────────────────────────────────────────────────────┐
│  Public: /                   LandingPage (new)       │
│  Auth:   /login /register    (existing)              │
│  Flow:   /onboarding         OnboardingPage (new)    │
│          /dashboard          HomePage (rewritten)    │
│          /session/:id        SessionPage (extended)  │
└──────────────────────────────────────────────────────┘
                     │
                     ▼ HTTPS + cookie session
┌──────────────────────────────────────────────────────┐
│  FastAPI — existing routes (auth, sessions, turns,   │
│    events, artifacts, skills)                        │
│  + NEW: wealth_routes (/wealth/profile, /checklist)  │
└──────────────────────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────┐
│  Postgres 16                                         │
│   - users, auth_sessions                             │
│   - agent_sessions, session_events                   │
│   - artifacts                                        │
│   - wealth_profiles (NEW)                            │
│   - wealth_checklist_items (NEW)                     │
└──────────────────────────────────────────────────────┘
                     │
                     ▼ skill loader activates on keywords
┌──────────────────────────────────────────────────────┐
│  core/src/skill_packs/wealth_guide/                  │
│   SKILL.md · REFERENCE.md · tools.py · skill.py      │
└──────────────────────────────────────────────────────┘
```

## 3. Milestones

| Milestone | Deliverable | Est. |
|---|---|---|
| M0 — Postgres migration | SQLite → plain Postgres + Alembic migrations | 2 d |
| M1 — Landing page | Public `/` with full marketing sections | 2–3 d |
| M2 — Skill pack | `wealth_guide` pack: SKILL.md + 3 tools + tests | 2 d |
| M3 — Onboarding wizard | 4-step form → prompt → session kickoff | 2 d |
| M4 — Artifact renderers | PathComparisonCard, ActionChecklist, WealthSnapshotWidget | 2–3 d |
| M5 — Dashboard + polish | Wealth-focused dashboard, routing, empty states | 2 d |
| M6 — Compliance + launch | Disclaimers, privacy, terms, error states, analytics | 2 d |

**Total: ~2.5 weeks of focused work.**

Build order recommendation: M0 and M2 first (in parallel), then M1 and M3, then M4, then M5 and M6.

## 4. Milestone 0 — Postgres migration

### 4.1 Dependencies

Add to `core/pyproject.toml`:
```toml
asyncpg = "^0.29"
alembic = "^1.13"
```

### 4.2 Connection config

Env var: `DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/apex`

Local dev: `docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=apex postgres:16`

### 4.3 Schema — Alembic migration `0001_initial.py`

```sql
-- Users & auth
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE auth_sessions (
  token TEXT PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX auth_sessions_user_idx ON auth_sessions(user_id);
CREATE INDEX auth_sessions_expires_idx ON auth_sessions(expires_at);

-- Agent sessions & events (existing surface, just moved to Postgres)
CREATE TABLE agent_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  model TEXT NOT NULL,
  context_strategy TEXT NOT NULL,
  state TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX agent_sessions_owner_idx ON agent_sessions(owner_user_id, created_at DESC);

CREATE TABLE session_events (
  seq BIGSERIAL PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
  turn_id UUID,
  type TEXT NOT NULL,
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX session_events_session_seq_idx ON session_events(session_id, seq);

CREATE TABLE artifacts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  content_path TEXT NOT NULL,
  size_bytes BIGINT NOT NULL DEFAULT 0,
  checksum TEXT,
  finalized BOOLEAN NOT NULL DEFAULT FALSE,
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX artifacts_session_idx ON artifacts(session_id, created_at DESC);

-- Wealth guide — user-scoped state (design-principles §4.4)
CREATE TABLE wealth_profiles (
  user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  profile JSONB NOT NULL,
  latest_snapshot_session_id UUID REFERENCES agent_sessions(id) ON DELETE SET NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE wealth_checklist_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  session_id UUID NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
  artifact_id UUID NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
  item_index INT NOT NULL,
  completed BOOLEAN NOT NULL DEFAULT FALSE,
  completed_at TIMESTAMPTZ,
  UNIQUE (artifact_id, item_index)
);
CREATE INDEX wealth_checklist_user_idx ON wealth_checklist_items(user_id);
```

### 4.4 Code changes

- New: `core/src/agent/session/store_postgres.py` — `PostgresSessionStore` implementing `SessionStore` protocol
- New: `core/src/agent/session/archive_postgres.py` — `PostgresSessionArchive` for event log
- New: `core/src/agent/users/store.py` — `UserStore` protocol + Postgres impl (§4.4 of principles)
- Modified: `backend/apex_server/auth.py` — swap SQLite queries for `asyncpg`
- Modified: `backend/apex_server/deps.py` — build `asyncpg` pool in `build_default_app_state()`, inject via `AppState`

No call-site changes thanks to protocol-driven design. Grep:
```bash
grep -rn "sqlite" core/src/ backend/apex_server/
```
Every hit is inside a class implementing an existing protocol.

### 4.5 Data migration

Pre-launch, no users. Drop-and-recreate on fresh Postgres. Document in README.

### 4.6 Acceptance

- `alembic upgrade head` creates schema on fresh Postgres
- `make serve` boots against Postgres
- All backend tests pass against Postgres
- No `sqlite3` imports remain in `backend/apex_server/` or `core/src/agent/session/`

## 5. Milestone 1 — Landing page

### 5.1 Routing (`frontend/src/App.tsx`)

```tsx
<Route path="/" element={<LandingPage />} />                                    // public, new
<Route path="/login" element={<AuthPage mode="login" />} />                     // existing
<Route path="/register" element={<AuthPage mode="register" />} />               // existing
<Route path="/onboarding" element={<RequireAuth><OnboardingPage /></RequireAuth>} />  // new
<Route path="/dashboard" element={<RequireAuth><HomePage /></RequireAuth>} />   // moved from /
<Route path="/session/:sessionId" element={<RequireAuth><SessionPage /></RequireAuth>} /> // existing
<Route path="/privacy" element={<PrivacyPage />} />                             // new in M6
<Route path="/terms" element={<TermsPage />} />                                 // new in M6
```

Post-login redirect logic (see M5): first-timer → `/onboarding`, returning user → `/dashboard`.

### 5.2 New file — `frontend/src/pages/LandingPage.tsx`

Single-scroll layout with sections in order:

```
1. Nav bar          — logo left, "Sign in" text link + "Get started" button
2. Hero             — headline, subhead, CTA → /register
3. Problem strip    — 3 pain-point cards
4. How it works     — 3-step horizontal row with icons
5. Feature grid     — 6 features (§7.2 of thesis)
6. Positioning row  — "Not this. This." 4-row comparison table
7. Pricing          — Free / Premium ($29/mo) / Annual ($249/yr)
8. Compliance note  — footer disclaimer
9. Footer           — links to /privacy, /terms, contact
```

### 5.3 Copy (locked — pulled from thesis)

**Hero**
```
Advisor-grade clarity for people without advisor-grade access.

Know what to do with your money. Understand the tradeoffs.
Get a practical plan — without becoming a finance expert.

[Get your free wealth snapshot]  → /register

For high earners with $100K–$3M. Not a stock picker. Not a robo-adviser.
```

**Problem strip (3 cards)**
- "Budgeting apps stop being useful once you have surplus cash."
- "Advisers feel expensive, opaque, or sales-driven."
- "Robo-advisers are too generic to explain what matters for your situation."

**How it works**
1. Tell us your situation — income, cash, debt, RSUs, goals
2. See your reasonable paths — 3–4 options with plain-English tradeoffs
3. Get a practical next step — weekly action checklist + concept explainers

**Feature grid**
- Net-worth and cash-allocation snapshot
- Goal intake and time-horizon modeling
- Path comparison: cash, index, stocks, home, debt-first
- Plain-English concept explainers
- Risk and concentration checks
- Weekly action checklist

**Positioning**

| Not this | This |
|---|---|
| Random stock tips | Capital allocation framing |
| Generic robo-allocation | Tailored to your situation |
| Encyclopedic finance content | Only what matters for you |
| Expensive human advisers | Fraction of the cost |

**Pricing**
- **Free** — basic snapshot + 1 path comparison
- **Premium — $29/mo** — full path comparison, scenario modeling, weekly check-ins
- **Annual — $249/yr** — individual premium plan billed yearly at a discount

**Compliance footer**
> Wealth Guide provides educational financial information and scenario comparisons, not personalized investment advice. Not a registered investment adviser.

### 5.4 Acceptance

- Page renders without auth
- All CTAs route to `/register`
- Mobile responsive (Tailwind `sm` `md` `lg`)
- Lighthouse performance > 90

## 6. Milestone 2 — Wealth guide skill pack

### 6.1 Files

```
core/src/skill_packs/wealth_guide/
  ├── SKILL.md
  ├── REFERENCE.md
  ├── skill.py
  └── tools.py
core/tests/test_wealth_guide_skill.py
```

Mirror the structure of `core/src/skill_packs/stock_strategy/`.

### 6.2 `SKILL.md` — decision tree, not prose

```markdown
# Wealth Guide

You are a capital allocation guide for mass-affluent users ($100K–$3M in assets).
Your job is to reduce the user's decision space and explain tradeoffs clearly.
You are not a stock picker. You are not a licensed investment adviser.

## Workflow

1. Call `build_wealth_snapshot(income, cash, monthly_expenses, retirement, brokerage, rsus, home_equity, debt, goals)`.
   This returns an artifact_id and a situation classification.

2. Based on `snapshot.situation`, call `compare_paths(snapshot_id, paths=...)`:
   - cash_heavy          → ["T-bills", "split", "index"]
   - rsu_concentrated    → ["diversify", "split", "hold-with-hedge"]
   - home_saving         → ["T-bills", "split", "HYSA-only"]
   - long_term_builder   → ["index", "split", "mixed-stocks"]
   - debt_burdened       → ["debt-first", "split"]

3. If `snapshot.flags` includes "high_interest_debt", always include "debt-first" in the path set, even if not listed above.

4. If `snapshot.flags` includes "concentration_risk", always include a "diversify" path.

5. After the user selects a path, call `generate_action_checklist(snapshot_id, chosen_path)`.

## Hard rules (enforced by tool layer — do not bypass)

- Never emit specific buy/sell/hold instructions for individual securities.
- Use category names only (broad US index ETF, total bond market ETF) — never tickers as recommendations.
- Always frame outputs as educational scenario comparisons.
- Always use the user's actual numbers.
- Reduce options — do not add more choices than are genuinely relevant.
```

### 6.3 `tools.py` — three typed tools

```python
@tool(name="build_wealth_snapshot", is_read_only=True, compliance_scope="education")
def build_wealth_snapshot(
    income: float,
    cash: float,
    monthly_expenses: float,
    retirement: float = 0,
    brokerage: float = 0,
    rsus: float = 0,
    home_equity: float = 0,
    debt: dict[str, float] | None = None,
    goals: list[str] | None = None,
) -> str:
    """Returns artifact_id of kind 'wealth_snapshot'.
    Artifact JSON shape:
      {
        schema_version: 1,
        net_worth: float,
        liquid_net_worth: float,
        allocation: {cash, rsus, retirement, brokerage, home, debt},
        emergency_fund: {months_covered: float, target_months: 6},
        situation: "cash_heavy" | "rsu_concentrated" | "home_saving"
                 | "long_term_builder" | "debt_burdened",
        flags: ["high_interest_debt", "concentration_risk", "cash_drag", ...]
      }
    """

@tool(name="compare_paths", is_read_only=True, compliance_scope="education")
def compare_paths(snapshot_id: str, paths: list[str]) -> str:
    """Returns artifact_id of kind 'path_comparison'.
    Artifact JSON shape:
      {
        schema_version: 1,
        paths: [{
          name: str,
          headline: str,
          pros: [str, str, str],
          cons: [str, str, str],
          best_for: str,
          required_concepts: [str, str, str]
        }]  // length 3-4
      }
    """

@tool(name="generate_action_checklist", is_read_only=True, compliance_scope="education")
def generate_action_checklist(snapshot_id: str, chosen_path: str) -> str:
    """Returns artifact_id of kind 'action_checklist'.
    Markdown with week-grouped checkboxes. 4 weeks, ~3-5 items per week.
    """
```

All three:
- `is_read_only=True` → no approval needed
- `compliance_scope="education"` → policy enforces no-ticker-recommendation filter on output

### 6.4 `skill.py` — keyword registration

```python
KEYWORDS = [
    "wealth", "net worth", "savings", "invest", "investing", "allocation",
    "portfolio", "RSU", "employer stock", "home", "mortgage", "down payment",
    "debt", "student loan", "retirement", "401k", "IRA", "emergency fund",
    "treasury", "T-bill", "index fund",
]
```

Follow the same pattern as `stock_strategy/skill.py`.

### 6.5 Acceptance

`core/tests/test_wealth_guide_skill.py`:
- Pack discovers keywords
- Each tool registers with dispatcher
- Each tool produces a valid artifact given mock inputs
- `build_wealth_snapshot` classifies situations correctly (fixture profiles → expected class)
- `compare_paths` returns 3–4 paths, each with 3 pros and 3 cons
- Output validator rejects ticker symbols in assistant messages (`$AAPL`, `VTSAX`, etc.)

## 7. Milestone 3 — Onboarding wizard

### 7.1 Files

- New: `frontend/src/pages/OnboardingPage.tsx`
- New: `frontend/src/components/onboarding/FinancialProfileForm.tsx`
- New: `frontend/src/lib/wealthPrompt.ts`
- New: `frontend/src/types.ts` additions (`FinancialProfile`, `WealthSnapshot`, `PathComparison`)

### 7.2 Form structure — 4 steps

```
Step 1 — Income & Cash
  Annual income (required, number)
  Liquid cash / savings (required, number)
  Monthly expenses (required, number)

Step 2 — Existing Assets
  Retirement accounts (401k/IRA)  (default 0)
  Brokerage / taxable             (default 0)
  RSUs / vested company stock     (default 0)
  Home equity                     (default 0)

Step 3 — Debt
  Student loans      amount + interest rate
  Credit card debt   amount
  Other debt         amount

Step 4 — Goals (checkboxes)
  [ ] Buy a home          → time horizon (1–3 / 3–5 / 5+ yr)
  [ ] Build long-term wealth
  [ ] Pay down debt first
  [ ] Reduce employer stock concentration
  [ ] Keep more cash liquid / safety first
```

### 7.3 Submit flow

```ts
async function handleSubmit(profile: FinancialProfile) {
  // 1. Persist profile (user-scoped, used by dashboard)
  await postJSON("/wealth/profile", profile);

  // 2. Create session
  const session = await postJSON<Session>("/sessions", {
    model: "deepseek/deepseek-chat",
  });

  // 3. Fire first turn with deterministic prompt (design-principles §7)
  await postJSON(`/sessions/${session.id}/turns`, {
    user_input: buildWealthPrompt(profile),
  });

  // 4. Navigate to session view
  navigate(`/session/${session.id}`);
}
```

### 7.4 Prompt template (`wealthPrompt.ts`)

```
Here is my financial situation:

Income & cash:
- Annual income: ${income}
- Liquid cash/savings: ${cash}
- Monthly expenses: ${monthly_expenses}

Existing assets:
- Retirement accounts: ${retirement}
- Brokerage: ${brokerage}
- RSUs / company stock (vested): ${rsus}
- Home equity: ${home_equity}

Debt:
- Student loans: ${student_loans} at ${student_loan_rate}%
- Credit card debt: ${credit_card_debt}
- Other debt: ${other_debt}

Goals:
${goals_list}
${home_purchase_horizon_if_set}

Please:
1. Build my wealth snapshot.
2. Show me 3–4 reasonable paths with plain-English tradeoffs.
3. Identify the 3 concepts I should understand before deciding.
```

### 7.5 New backend routes — `backend/apex_server/routes/wealth_routes.py`

```
POST   /wealth/profile
  body: FinancialProfile
  action: upsert wealth_profiles row for current user
  returns: 204

GET    /wealth/profile
  returns: FinancialProfile | 404

GET    /wealth/checklist
  returns: aggregate of wealth_checklist_items for current user's latest session
           { session_id, artifact_id, items: [{idx, text, completed}] }

POST   /wealth/checklist/toggle
  body: { artifact_id, item_index, completed }
  action: upsert into wealth_checklist_items
  returns: 204
```

All endpoints use `require_user` dependency, scope queries by `user.id`.

Register in `backend/apex_server/app.py`:
```python
from apex_server.routes.wealth_routes import router as wealth_router
app.include_router(wealth_router)
```

### 7.6 Acceptance

- 4 steps validate before advancing; back button preserves state
- Profile persists to Postgres before session creation
- Session page loads with SSE open, receives first streaming tokens within 500ms
- Agent produces `wealth_snapshot` + `path_comparison` artifacts without user follow-up

## 8. Milestone 4 — Artifact renderers

### 8.1 Files

```
frontend/src/components/artifacts/
  ├── PathComparisonCard.tsx     (new)
  ├── ActionChecklist.tsx        (new)
  └── ArtifactPanel.tsx          (modified — kind dispatch)
frontend/src/components/wealth/
  └── WealthSnapshotWidget.tsx   (new)
```

### 8.2 Kind dispatch in `ArtifactPanel.tsx`

```tsx
function renderArtifact(artifact: Artifact) {
  switch (artifact.kind) {
    case "wealth_snapshot":   return <WealthSnapshotWidget artifact={artifact} />;
    case "path_comparison":   return <PathComparisonCard artifact={artifact} />;
    case "action_checklist":  return <ActionChecklist artifact={artifact} />;
    case "markdown":          return <MarkdownRenderer artifact={artifact} />;
    case "code":              return <CodeRenderer artifact={artifact} />;
    // ...existing kinds
  }
}
```

### 8.3 `PathComparisonCard.tsx`

Input: `path_comparison` JSON. Renders horizontal row of cards (stack on mobile).

```
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
│ Treasury-heavy      │  │ Split path          │  │ Long-term ETF       │
│ Safety + liquidity  │  │ Balanced            │  │ Wealth building     │
├─────────────────────┤  ├─────────────────────┤  ├─────────────────────┤
│ ✓ No volatility     │  │ ✓ Some growth       │  │ ✓ Highest long-term │
│ ✓ 4–5% yield        │  │ ✓ Still liquid      │  │ ✓ Simple            │
│ ✓ Fully liquid      │  │ ✓ Lower risk        │  │ ✓ Low fees          │
│ ✗ Trails equities   │  │ ✗ More complexity   │  │ ✗ Full volatility   │
│ ✗ Inflation drag    │  │ ✗ Rebalancing       │  │ ✗ Not for <5yr goal │
│ Best: home < 3yr    │  │ Best: undecided     │  │ Best: 5yr+ horizon  │
│ Concepts: liquidity │  │ Concepts: rebalance │  │ Concepts: horizon   │
│ [Choose this path]  │  │ [Choose this path]  │  │ [Choose this path]  │
└─────────────────────┘  └─────────────────────┘  └─────────────────────┘
```

"Choose this path" fires a new turn:
```ts
await postJSON(`/sessions/${sessionId}/turns`, {
  user_input: `I want the ${path.name} path. Give me my action checklist.`
});
```

### 8.4 `ActionChecklist.tsx`

Input: `action_checklist` markdown artifact. Interactive checkboxes persisted to Postgres:

```tsx
async function onToggle(idx: number, completed: boolean) {
  // optimistic update
  setLocalState(idx, completed);
  try {
    await postJSON("/wealth/checklist/toggle", {
      artifact_id: artifact.id,
      item_index: idx,
      completed,
    });
  } catch {
    setLocalState(idx, !completed);  // rollback
  }
}
```

Render:
```
Week 1
[✓] Open a Treasury Direct account
[ ] Calculate your emergency fund target (3–6 months = $39k)
[ ] Pull your RSU vesting schedule

Week 2
[ ] Open a taxable brokerage account
[ ] Read: What is an index fund? (2 min)
...
```

### 8.5 `WealthSnapshotWidget.tsx`

Input: `wealth_snapshot` JSON. Renders as compact header block on `SessionPage` when the session has a `wealth_snapshot` artifact.

```
Net worth: $320,000             Situation: RSU-concentrated, cash-heavy
Liquid: $120,000

[████████████░░░░░░░░░░░░░] Cash $120k (37%)
[████░░░░░░░░░░░░░░░░░░░░░] RSUs  $80k (25%)
[████████████░░░░░░░░░░░░░] 401k  $120k (37%)

⚠ $85K above emergency fund target — unallocated
⚠ 25% of net worth in single employer stock
```

### 8.6 Acceptance

- Renderers handle streaming updates (re-render on `artifact_patch`)
- "Choose this path" fires a new turn and scrolls chat to show agent response
- Checklist toggles persist to Postgres and survive page refresh
- `WealthSnapshotWidget` only shows when session has snapshot artifact

## 9. Milestone 5 — Dashboard + polish

### 9.1 Rewritten `HomePage.tsx`

Data sources: `GET /wealth/profile`, `GET /wealth/checklist`, `GET /sessions`.

```
┌──────────────────────────────────────────┐
│  Welcome back, Tianye                    │
│                                          │
│  Your wealth snapshot                    │
│  Net worth: $320,000                     │
│  Last updated: 2 days ago                │
│  [Update my situation] → /onboarding     │
│                                          │
│  Active plan: Treasury-heavy path        │
│  This week's actions (2 of 4 done)       │
│  ✓ Open Treasury Direct account          │
│  ✓ Calculate emergency fund target       │
│  ☐ Pull RSU vesting schedule             │
│  ☐ Read: What is a T-bill?               │
│  [Open full plan] → /session/:id         │
│                                          │
│  Previous sessions:                      │
│  - Wealth snapshot · 2 days ago          │
│  - Home purchase scenario · 1 week ago   │
└──────────────────────────────────────────┘
```

### 9.2 Post-auth redirect

Update `frontend/src/components/auth/AuthPage.tsx`:

```ts
// After successful login/register:
const profile = await fetchOrNull("/wealth/profile");
navigate(profile ? "/dashboard" : "/onboarding");
```

### 9.3 Empty states

- Dashboard with no profile → big CTA "Start my wealth snapshot" → `/onboarding`
- Session before first artifact → skeleton loader "Analyzing your situation…"
- Checklist not yet generated → "Select a path above to get your action plan"

### 9.4 Acceptance

End-to-end flow:
```
/ (unauthed) → /register → /onboarding → wizard → /session/:id
  → snapshot + paths render → click path → checklist renders
  → back to /dashboard → plan summary visible with checked items
```

All transitions under 500ms (SSE connect + first token).

## 10. Milestone 6 — Compliance + launch

### 10.1 Compliance surfaces

- Landing page footer disclaimer (already in M1)
- In-app banner on first session of the day: "Educational scenario comparison — not personalized investment advice"
- `/privacy` page: financial data handling (Postgres hosting region, encryption at rest, retention)
- `/terms` page

### 10.2 Error handling

- Session creation failure → toast + stay on onboarding, preserve form state
- SSE disconnect > 30s → banner + auto-reconnect (existing behavior, verify)
- Tool execution failure → graceful "couldn't build snapshot, try again"
- Postgres connection failure → 503 with `Retry-After` header

### 10.3 Analytics (optional, PostHog or Plausible)

Events only (no PII):
```
landing_viewed · register_started · onboarding_started · onboarding_completed
snapshot_built · path_selected · checklist_item_completed · session_resumed
```

### 10.4 Acceptance

- All user-facing pages have disclaimer
- `/privacy` and `/terms` reachable from footer
- No unhandled errors in Sentry over 24h run
- Postgres connection pool metrics exposed on `/health`

## 11. File inventory

### New files

| Path | Milestone |
|---|---|
| `core/alembic.ini` | M0 |
| `core/alembic/versions/0001_initial.py` | M0 |
| `core/src/agent/session/store_postgres.py` | M0 |
| `core/src/agent/session/archive_postgres.py` | M0 |
| `core/src/agent/users/store.py` | M0 |
| `core/src/skill_packs/wealth_guide/SKILL.md` | M2 |
| `core/src/skill_packs/wealth_guide/REFERENCE.md` | M2 |
| `core/src/skill_packs/wealth_guide/skill.py` | M2 |
| `core/src/skill_packs/wealth_guide/tools.py` | M2 |
| `core/tests/test_wealth_guide_skill.py` | M2 |
| `backend/apex_server/routes/wealth_routes.py` | M3 |
| `frontend/src/pages/LandingPage.tsx` | M1 |
| `frontend/src/pages/OnboardingPage.tsx` | M3 |
| `frontend/src/pages/PrivacyPage.tsx` | M6 |
| `frontend/src/pages/TermsPage.tsx` | M6 |
| `frontend/src/components/onboarding/FinancialProfileForm.tsx` | M3 |
| `frontend/src/components/artifacts/PathComparisonCard.tsx` | M4 |
| `frontend/src/components/artifacts/ActionChecklist.tsx` | M4 |
| `frontend/src/components/wealth/WealthSnapshotWidget.tsx` | M4 |
| `frontend/src/lib/wealthPrompt.ts` | M3 |

### Modified files

| Path | Change | Milestone |
|---|---|---|
| `core/pyproject.toml` | Add asyncpg, alembic | M0 |
| `backend/apex_server/auth.py` | SQLite → asyncpg | M0 |
| `backend/apex_server/deps.py` | Postgres pool in AppState | M0 |
| `backend/apex_server/app.py` | Register wealth_router | M3 |
| `core/src/agent/session/store.py` | Default to Postgres impl | M0 |
| `frontend/src/App.tsx` | Add routes, move dashboard to /dashboard | M1, M3 |
| `frontend/src/pages/HomePage.tsx` | Wealth-focused dashboard | M5 |
| `frontend/src/components/artifacts/ArtifactPanel.tsx` | Kind-based renderer dispatch | M4 |
| `frontend/src/components/auth/AuthPage.tsx` | Post-auth redirect logic | M5 |
| `frontend/src/store.ts` | Add onboarding + checklist state | M3, M4 |
| `frontend/src/types.ts` | Add `FinancialProfile`, `WealthSnapshot`, `PathComparison` | M2, M3 |

## 12. Environment variables

```
# Backend
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/apex
APEX_SESSION_COOKIE_SECURE=true           # production only
APEX_DEV_BYPASS_AUTH=1                    # local dev, ignored when ENV=production
ENV=development                           # or production
LLM_PROVIDER=deepseek                     # existing
DEEPSEEK_API_KEY=...                      # or OPENAI_API_KEY, etc.
ARTIFACT_ROOT=/var/apex/artifacts         # filesystem for MVP

# Frontend (Vite)
VITE_API_BASE=http://localhost:8000
```

## 13. Hosting recommendation

| Component | Host | Notes |
|---|---|---|
| Frontend | Vercel or Cloudflare Pages | Static build, branch previews |
| Backend | Fly.io or Railway | One container, simple deploy |
| Postgres | **Neon** (serverless) or **Railway Postgres** | Free tier viable for MVP |
| Artifacts (FS) | Fly.io volume or Railway volume | Move to S3 in phase 4 |

Recommended combo: **Vercel + Fly.io + Neon.** All have free tiers that cover early usage; scale-up is linear.

## 14. Open questions (resolve during build)

| # | Question | Default |
|---|---|---|
| 1 | `UserStore` — new interface or extend `SessionStore`? | New interface |
| 2 | `compliance_scope` metadata or separate policy object? | Metadata |
| 3 | Disclaimer — chat message or dedicated event? | Dedicated event |
| 4 | Version `wealth_snapshot` schema from day 1? | Yes, `schema_version: 1` |
| 5 | Checklist completion — Postgres or client-only? | Postgres (enables dashboard summary) |
| 6 | Production Postgres host? | Neon |
| 7 | Do we ship a `/wealth/start` convenience wrapper? | No — frontend calls `/sessions` + `/turns` directly |

## 15. Out of scope for MVP

- Plaid / account linking
- Tax optimization engine
- Estate planning
- Multi-user households
- Mobile native app
- Notifications / email drip
- Real-time market data beyond current rates
- Portfolio rebalancing execution
- MCP exposure of coach tools
- Redis event bus (web-platform-plan phase 3)
- S3 artifacts (phase 4)

All are credible post-MVP. None belong in the first release.

## 16. Definition of done for MVP

An unauthenticated visitor can:
1. Land on `/`, read the pitch, click "Get started"
2. Register, complete onboarding wizard
3. Receive a wealth snapshot + 3–4 path comparisons within 30 seconds
4. Select a path and receive a 4-week action checklist
5. Return the next day, log in, see their dashboard with checklist progress
6. Mark items complete; progress persists
7. Start a new session to explore a scenario; profile carries over without re-entry

Every compliance test in §8 of the design-principles doc passes. Zero tickers in any assistant message. Zero unhandled errors in Sentry over a 24h smoke run.

When these are all true, M6 is complete and MVP is ready to launch.
