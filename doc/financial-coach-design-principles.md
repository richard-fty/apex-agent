# Financial Coach — MVP Design Principles

> Companion to [mass-affluent-wealth-guide-thesis.md](mass-affluent-wealth-guide-thesis.md) (the *why*) and [design-spec.md](design-spec.md) (the agent core). This document is the *how* for the product layer.
>
> **Purpose:** give reviewers a single page that captures the product principles, the agent-design decisions, and what we are and are not changing in the managed-agent core.

## 1. Product identity

**What this is.** An AI financial coach for the mass affluent — $100K–$3M in assets, high earners who need clarity on capital allocation, not stock tips.

**What this is not.** Not a licensed investment adviser. Not a stock picker. Not a robo-allocator. Not a budgeting app. Not a human-advisor simulator.

**Position.** "Advisor-grade structure and clarity for people without advisor-grade access."

## 2. Product principles (the things we always do)

These are the non-negotiables. Every feature decision gets measured against these.

### 2.1 Reduce the decision space, don't expand it
Always present 3–4 paths, never more. A user with no framework sees fewer options, not a longer menu. Adding a path requires removing one.

### 2.2 Adaptive education, not encyclopedic
Teach the exact concepts the user needs to decide between *their* paths. Don't drop a finance curriculum. Three concepts per session is the target.

### 2.3 Structured artifacts over prose
Snapshots, path comparisons, and checklists are typed JSON/markdown artifacts with renderers — not long assistant messages. The UI decides how to show them. Prose is for framing and tradeoffs, not data.

### 2.4 Compliance by construction
Hard rules are enforced in the tool layer, not in prompt text. The agent physically cannot emit "buy VTSAX" as a recommendation because the tool output schema doesn't allow it. Prompts reinforce what tools already guarantee.

### 2.5 Framework consistency across users
Two users with similar situations should get the same framework, the same path set, the same concept list. Individual numbers change; the structure does not. This is testable in the eval suite.

### 2.6 Trust is earned by reasoning, not confidence
Every recommendation is framed as "given your situation and these assumptions, these are reasonable paths." Never "this is the best path." Tradeoffs are surfaced, not hidden.

### 2.7 User-scoped state is first-class
A user's financial profile and checklist progress live *outside* any single session. Sessions are conversations; the profile is ground truth. Users can start new sessions without re-entering their situation.

## 3. Agent design — extend, don't upgrade

**Short answer: the current [design-spec.md](design-spec.md) does not need an upgrade. It needs four small, additive extensions.**

The managed-agent shape (session / harness / sandbox / tools / orchestration) is correct for this product. The five virtualized surfaces and the `execute(name, input) -> str` universal hands contract all stay exactly as-is. No new architectural primitives.

What this product needs is already supported at existing extension points:

| Product need | Mechanism in design-spec | Status |
|---|---|---|
| Wealth-specific behavior | Skill packs (§7.1) | Extension point — add `wealth_guide` pack |
| Typed wealth artifacts | Artifact store + event schema | Additive — new `kind` values |
| Compliance rules | Tool metadata + policy (§5) | Additive — new metadata tag |
| Approval UX (education is read-only) | Approval model (§7.3) | Reuse as-is — wealth tools are all `is_read_only=True` |
| User profile persistence | Out of scope in design-spec | **New** — user-scoped store, not session-scoped |

So: one genuinely new concept (user-scoped state), plus three additive extensions at existing extension points.

## 4. The four extensions

### 4.1 `wealth_guide` skill pack (additive, no core change)

A new pack under `core/src/skill_packs/wealth_guide/` that mirrors the existing `stock_strategy/` shape:

- `SKILL.md` — decision tree for the agent (not prose)
- `REFERENCE.md` — compact frameworks (liquidity, time horizon, concentration risk)
- `tools.py` — three typed tools: `build_wealth_snapshot`, `compare_paths`, `generate_action_checklist`
- `skill.py` — keyword registration

This is exactly what the skill pack extension point was designed for. No runtime change.

### 4.2 New artifact kinds (additive to event schema)

Add three kinds to the existing artifact system:

- `wealth_snapshot` — JSON: net worth, allocation, situation class, flags
- `path_comparison` — JSON: 3–4 paths with pros/cons/best_for/concepts
- `action_checklist` — markdown: week-grouped checklist

These slot into the existing `artifact_created` / `artifact_patch` / `artifact_finalized` event flow. Frontend adds renderers; nothing in the runtime changes.

### 4.3 Compliance metadata on tools (small additive extension)

Today every tool carries `is_read_only`, `is_destructive`, `is_networked`, `mutates_state`. Add one more:

```python
compliance_scope: Literal["education", "general"] | None = None
```

Wealth-guide tools declare `compliance_scope="education"`. Policy reads the metadata to enforce:
- never auto-escalate permissions on education-scoped tools
- block any tool output that contains specific ticker buy/sell recommendations (regex check on output before `emit_event`)
- require the standard disclaimer event to accompany any education-scoped turn

**This is one field added to existing metadata. No new interfaces.**

### 4.4 User-scoped state (genuinely new concept)

The design-spec treats sessions as the only durable surface. This product needs two things that live *outside* a session:

- **Financial profile** — the user's current numbers, updated when they re-onboard
- **Checklist progress** — per-item completion across sessions

Add a `UserStore` alongside `SessionStore`:

```python
class UserStore(Protocol):
    async def get_profile(self, user_id: str) -> WealthProfile | None: ...
    async def put_profile(self, user_id: str, profile: WealthProfile) -> None: ...
    async def get_checklist(self, user_id: str) -> list[ChecklistItem]: ...
    async def toggle_checklist_item(self, user_id: str, artifact_id: str, idx: int, done: bool) -> None: ...
```

Sessions can call the `UserStore` (via a native skill tool, e.g. `load_user_profile`) to hydrate context without re-asking the user.

This is one new interface, same shape as the existing session store. The managed-agent core is unaffected.

## 5. Tool registration strategy

One of the more load-bearing decisions, called out because it shapes every tool we build.

### 5.1 Three lanes

| Lane | When to use | Example |
|---|---|---|
| **Native skill pack tool** | Tool produces structured data the frontend renders, or needs DB/auth context | `build_wealth_snapshot`, `save_profile` |
| **CLI via `shell_exec` + SKILL.md** | Tool is a side-effect on shell (existing binary, file work, fetches) | `wkhtmltopdf`, `curl` for T-bill rates |
| **MCP** | Explicitly out of scope for MVP | — |

### 5.2 Why no MCP in MVP

MCP tool schemas inject into every turn's context. For a single-product agent where tools are not reused across products, that context cost buys nothing. The existing skill pack + shell pattern is lighter and already proven in `stock_strategy/`.

Revisit MCP when:
- we build a second product that could share tools (e.g., retirement planner)
- we want to expose the coach's tools to other agents or external clients

### 5.3 SKILL.md is a decision tree, not prose

This is a style rule that makes agent behavior testable:

```
Bad:   "You are a wealth coach. Help users with their finances. Be smart."
Good:  "After build_wealth_snapshot, read snapshot.situation:
         - cash_heavy          → compare_paths(['T-bills', 'split', 'index'])
         - rsu_concentrated    → compare_paths(['diversify', 'split', 'hold'])
         - debt_burdened       → compare_paths(['debt-first', 'split'])
        If snapshot.flags has 'high_interest_debt', always include 'debt-first'."
```

Decision-tree SKILL.md lets the eval suite assert exact tool sequences for given profiles. Prose SKILL.md cannot.

## 6. Session shape

Every wealth-guide session follows the same event shape. This is the contract the eval suite enforces.

```
user_message            ← structured onboarding prompt (or follow-up)
assistant_token*        ← framing / brief rationale
tool_call_started       ← build_wealth_snapshot
tool_call_finished      ← snapshot artifact
artifact_created        ← wealth_snapshot
tool_call_started       ← compare_paths
tool_call_finished      ← path_comparison artifact
artifact_created        ← path_comparison
assistant_message       ← "Here are 3 reasonable paths. The 3 concepts you need…"
turn_finished
stream_end

(user picks a path in the UI, which fires a new turn)

user_message            ← "I want the Treasury-heavy path"
tool_call_started       ← generate_action_checklist
tool_call_finished      ← checklist artifact
artifact_created        ← action_checklist
assistant_message       ← "Your 4-week plan is ready."
turn_finished
stream_end
```

This shape is what the eval suite scores for task success, tool selection, and framework consistency.

## 7. Onboarding: structured > free-form

A design choice worth calling out: **first-turn input is a structured form, not a chat message.**

The onboarding wizard collects income, cash, debt, assets, goals. On submit, the frontend serializes into a deterministic prompt template and fires it as the first user message.

Why this matters:
- **Framework consistency** (§2.5) requires structured inputs. Free-form chat gives wildly different first turns.
- **Eval tractability** — we can replay recorded profiles and assert behavior.
- **Compliance** — structured inputs make the "we are acting on X inputs" statement auditable.

After onboarding, chat is free-form again. But the first turn is always the deterministic template.

## 8. Eval suite extensions

The existing eval suite (§7.5 of design-spec) covers the core runtime. This product adds one tier:

- **T4 — Wealth Coach** scenarios under `core/src/scenarios/coach_*/`
  - `coach_cash_heavy` — user with $100k cash, $180k income, no debt
  - `coach_rsu_concentrated` — user with 40% net worth in employer stock
  - `coach_home_saving` — user targeting home in 2 years
  - `coach_debt_burdened` — user with $50k student loans at 8%
  - `coach_compliance_breach` — red-team: try to get the agent to recommend a ticker

For each scenario, the runner asserts:
1. The correct tools were called in the correct order
2. The path set returned matches the situation class
3. No ticker-style recommendation appears in any assistant message
4. Disclaimer event present in every turn with education-scoped tool calls

Release gate: zero regressions on compliance scenarios.

## 9. What we are not changing in the agent core

To make review easy, here is what explicitly stays identical:

- Managed-agent shape (session / harness / sandbox / tools / orchestration)
- `execute(name, input) -> str` universal hands contract
- Event schema (we add *values* to existing types, not new types)
- Approval model (`allow | ask | deny` by metadata)
- Harness statelessness + `wake(session_id)`
- Sandbox interface (`BaseSandbox`, `LocalSandbox`, `DockerSandbox`)
- LLM brain adapter (LiteLLM)
- TUI as event consumer

If a reviewer finds a change in this list, that is a bug.

## 10. Non-goals for MVP

- Plaid / account linking (manual entry only)
- Tax optimization engine
- Estate planning
- Multi-user households
- Mobile native app
- Notifications / email drip
- Sharing plans with third parties
- Real-time market data beyond current rates
- Portfolio management / rebalancing execution
- MCP exposure of coach tools

All are credible post-MVP. None belong in the first release.

## 11. Review checklist

For a reviewer to approve this design, confirm:

- [ ] The seven product principles (§2) are the right ones for mass-affluent users
- [ ] The four extensions (§4) are minimal and fit existing extension points
- [ ] The tool-registration strategy (§5) correctly defers MCP
- [ ] Session shape (§6) is enforceable by the eval suite
- [ ] Structured onboarding (§7) is worth the UX constraint
- [ ] Compliance approach (§4.3) is strong enough for "education, not advice" framing
- [ ] Non-goals (§10) are genuinely deferrable

If all seven check, this design is approved and we build to [wealth-guide-implementation-plan.md](wealth-guide-implementation-plan.md) (forthcoming).

## 12. Open questions for review

| # | Question | Default |
|---|---|---|
| 1 | Should `UserStore` be a new interface or absorbed into `SessionStore` with a `user_id` scope? | New interface — cleaner boundary |
| 2 | Is `compliance_scope` metadata the right shape, or should it be a separate policy object? | Metadata — matches existing pattern |
| 3 | Should the disclaimer be a chat message or a dedicated event type? | Dedicated event — easier to assert in eval |
| 4 | Do we version the `wealth_snapshot` schema from day 1? | Yes — `schema_version: 1` field, cheap to add |
| 5 | Is the 3-concept-per-session rule a product principle or a skill-pack-only rule? | Skill-pack rule — could change per vertical |
