# LT1 — Equity Research Briefing (long-horizon scenario design)

Status: draft · Owner: tf275@cornell.edu · Last updated: 2026-04-21

One document, one scenario. This covers:

- the **definition of long-horizon** used throughout the repo (§0)
- the 5-minute task we will run the agent against (§3)
- the **`web_research` tool enhancement** — fuses `web_search` + `web_fetch` into a
  single parallel call (§4)
- the **sidebar search-card UI enhancement** — `SearchCardsPanel` next to the
  existing `ActivityBar` (§5)
- the **Word-document artifact** (`.docx`, not markdown) the agent must produce (§6)
- the **enhanced `stock_strategy` skill** that packages all the repetitive steps so
  the user only has to say "brief me on $TICKER" (§7)
- the eval-harness wiring and pass/fail gates (§8)
- the **verification playbook** — exactly how you prove the scenario works (§9)

Built on what already exists in the repo:

- `core/src/tools/web.py:15-114` — today's `WebSearchTool` + `WebFetchTool` (both
  sequential, both "call one at a time" per `managed_runtime.py:628-630`).
- `core/src/skill_packs/stock_strategy/` — existing skill with
  `fetch_market_data`, `compute_indicator`, `generate_chart`, `run_backtest`.
- `core/src/scenarios/stock_strategy/` — existing eval scenario plumbing we reuse.
- `frontend/src/components/chat/ActivityBar.tsx:14-57` — the component the sidebar
  cards slot next to.
- `core/src/eval/runner.py:455-510` — the benchmark CLI (`--timeout 300` is already
  the 5-minute cap).

---

## 0. What we mean by "long-horizon"

"Long-horizon" is an overloaded term. In this repo it is a conjunction, not a
single knob — a task is long-horizon only if **every** line below is true of
it. The LT1 briefing scenario is designed to satisfy all of them on purpose.

| Dimension | Threshold for "long-horizon" | How LT1 meets it |
| --------- | ---------------------------- | ---------------- |
| **Wall-clock** | ≥ 3 min, target 5 min, hard-capped at `--timeout 300` (`eval/runner.py:473`) | Task prompt explicitly says "You have 5 minutes"; runner kills at 300 s |
| **Step count** | ≥ 20 LLM turns before a final artifact is written | `max_steps: 30`; typical run is 22–28 |
| **Tool diversity** | ≥ 4 distinct tool names in the trace, across ≥ 2 tool groups | `web_research` + `fetch_market_data` + `compute_indicator` + `generate_chart` + `write_file` + `run_command` (6 names, 3 groups) |
| **Compositional depth** | Output of one tool is required input to another, ≥ 2 hops | `web_research` → news items → `render.py` source list; `fetch_market_data` → `compute_indicator` → `generate_chart` → chart PNG embedded in `.docx` |
| **Intermediate artifacts** | ≥ 1 file on disk that is *not* the final deliverable but is needed to produce it | `NVDA_chart.png`, `render.py`, and an intermediate JSON dump of news items |
| **Recovery tolerance** | The run must survive a mid-run kill (T1.3 recovery test) and resume from disk, not from memory | All intermediates are file-based; `render.py` is idempotent and re-runnable |
| **Grading is verifiable** | Final artifact is machine-gradable beyond "it exists" | `.docx` is parsed with `python-docx`; headings, inline images, hyperlink count all asserted |
| **Not solvable from cache** | Prompt requires information past the model's training cutoff | "Most recent" quarterly results + today's price force live fetches |

What specifically does **not** make a task long-horizon, by this definition:

- A single large prompt-and-response (no tool calls).
- A long chain of the *same* tool (e.g., 30 sequential `read_file` calls — step
  count without diversity or composition).
- Any task where the model could plausibly answer from training data alone.

This is the operational definition the eval suite uses — `doc/eval-suite.md`
calls the tier LT1 and this scenario is the canonical LT1 member.

---

## 1. Why this scenario

Equity research is a near-perfect long-horizon test because it naturally chains
every capability we care about in one bounded, gradable task:

1. Live-web search (several competing narratives — earnings, analyst notes, filings).
2. Page reading (snippets are never enough).
3. Numeric data pull (market OHLCV from `fetch_market_data`).
4. Script authoring + execution (compute indicators and render the document).
5. Structured artifact (`.docx`, not markdown — forces *real* document tooling).
6. Budget discipline (5 min, ≤ $1.50, forbidden tools must not appear).

The current `stock_strategy` scenario tests steps 3–4 only. This one stretches the
agent across all six without inventing a new domain — we build on the skill the
team already trusts.

## 2. Non-goals

- Not a trading signal. The scenario grades *process*, not the investment thesis.
- Not a replacement for `research_and_report`. That scenario stays as the easier
  filesystem-only baseline; LT1 is the hard live-web tier above it.
- Not a new frontend framework. The UI work is a single additive component.

## 3. The task

Trigger phrase the user types:

> `Brief me on NVDA.`

What the skill expands it to (§7 shows the prompt template):

> You have 5 minutes. Produce an equity-research briefing on **NVDA** as a Word
> document. Use the `web_research` tool to gather the five most-recent authoritative
> stories (earnings releases, SEC filings, Reuters/Bloomberg/FT). Use
> `fetch_market_data` + `compute_indicator` for the last 6 months of OHLCV, RSI(14),
> and SMA(50/200). Write `results/lt1_briefing/render.py` that builds a `.docx`
> file at `results/lt1_briefing/NVDA_briefing.docx` with sections *Executive
> Summary*, *Price & Indicators* (embed the chart PNG), *News & Catalysts* (bulleted
> with hyperlinks), *Risks*, *Sources* (numbered URL list). Run the script. The
> final artifact is the `.docx` file. Stop after it is written.

### Pass/fail gates

| # | Gate | Checked by |
| - | ---- | ---------- |
| G1 | `NVDA_briefing.docx` exists and opens as a valid OOXML document | evaluator uses `python-docx` to read it |
| G2 | Document contains every required section heading (Word heading style, not plain text) | evaluator walks paragraphs |
| G3 | *Price & Indicators* embeds at least one inline image | `doc.inline_shapes` ≥ 1 |
| G4 | *Sources* contains ≥ 5 clickable hyperlinks; each URL appears somewhere in the agent's trace | evaluator + trace join |
| G5 | `expected_tools` all present; `forbidden_tools` (`rm`, raw `web_fetch`) absent | existing base evaluator |
| G6 | Wall-clock ≤ 300 s, cost ≤ $1.50 | runner |
| G7 | `web_research` called ≤ 3 times total (budget on tool-call explosion — see §4) | trace counter |

G7 is the measurable win from the new combined tool: today the same task spikes to
10–20 `web_fetch` calls.

---

## 4. New tool: `web_research` (combined search + parallel fetch)

### 4.1 Problem we are fixing

Today the agent has to call `web_search` once and then `web_fetch` N times, each
round-trip through the LLM loop. In `managed_runtime.py:628-630`:

```python
for tool_call in parsed_calls:
    async for event in self._handle_tool_call(tool_call, trace=trace):
        yield event
```

Tools are dispatched strictly sequentially, so a 5-URL research pass is 6 LLM
turns + 6 context expansions + 6 chances to drift. This is the dominant cost on
the existing research scenarios.

### 4.2 Contract

New tool lives in `core/src/tools/web.py` alongside the current two. We keep
`WebSearchTool` and `WebFetchTool` registered but mark them non-preferred in the
skill/system prompt — `web_research` becomes the canonical path.

```python
class WebResearchTool(BuiltinTool):
    name = "web_research"
    description = (
        "Search the web AND fetch the top pages in one call. "
        "Returns each result's url, title, snippet, and cleaned page text. "
        "Prefer this over calling web_search + web_fetch separately."
    )
    parameters = [
        ToolParameter(name="query",      type="string"),
        ToolParameter(name="num_results",type="integer", required=False, default=5),
        ToolParameter(name="fetch_top",  type="integer", required=False, default=3,
                      description="How many of the top results to also fetch. 0 = search only."),
        ToolParameter(name="max_chars",  type="integer", required=False, default=4000,
                      description="Per-page character cap after fetch."),
    ]
```

### 4.3 Behaviour

```
search_web(query, num_results)
    ↓
results: [{title, url, snippet}, …]
    ↓
asyncio.gather(*[_fetch(r.url, max_chars) for r in results[:fetch_top]])
    ↓
return structured payload: { query, results: [{title, url, snippet, text?, fetch_error?}] }
```

Key properties:

- **Parallel fetch.** One `asyncio.gather` across the top-N URLs — the
  speedup is what makes G7 achievable inside a 5-minute window.
- **Partial failure is fine.** A timed-out fetch becomes `fetch_error: "timeout"`
  on that one result; the rest are returned. The agent does not have to retry
  the whole thing.
- **Deduplication.** Hash-dedupe by URL across calls in the same session; a
  second `web_research` for a near-identical query reuses the cache.
- **Budget fence.** `fetch_top` is capped at 5 at the tool level so a
  hallucinated `fetch_top=50` cannot blow the budget.
- **Emits one structured event, not N.** The turn orchestrator receives a
  single `tool_call.completed` event with the combined payload; the UI
  renders N cards from it (§5).

### 4.4 Compatibility

- Leave `web_search` / `web_fetch` in place — skills or tests that call them
  directly still work.
- Update system prompt / `stock_strategy` `SKILL.md` (§7) to steer toward
  `web_research` for any "look up and read" intent.
- Tool-use tests in `core/tests/` that assert `web_search` call counts need to
  accept `web_research` as equivalent.

### 4.5 Unit test bar

New tests in `core/tests/tools/test_web_research.py`:

1. Happy path: returns N results, top-K with `text`, rest with snippet only.
2. Fetch timeout on one URL → `fetch_error` on that one, others complete.
3. `fetch_top=0` → search-only, no network calls beyond search.
4. Same query called twice in same session → second call is cache hit.

---

## 5. UI: search-card sidebar

### 5.1 What we want (from the reference screenshot)

A panel that, as the agent is researching, shows a vertical list of cards — one
per URL — with:

- a small favicon or source logo
- an ago-timestamp ("14 hours ago")
- a title, styled as a link, rendering the real URL
- a one-line snippet

Exactly the Perplexity / Claude.ai Sources style in the user-provided image.

### 5.2 Where it lives

`frontend/src/components/chat/` gains a new component:

```
SearchCardsPanel.tsx   ← new
ActivityBar.tsx        ← unchanged
```

`ActivityBar` stays for the "Thinking… / Running command…" live strip. It does
**not** become the cards host — the cards must persist *after* a `web_research`
call finishes so the user can still click the links, so they live in their own
panel that pins to the right edge of the chat while an artifact-free session is
active (and slides under the artifact panel when an artifact is open).

### 5.3 Data flow

1. `web_research` emits its structured payload through the existing
   `tool_call.completed` event.
2. Backend event schema adds an optional `search_results: {title, url, snippet,
   source, timestamp}[]` field populated only for `web_research`.
3. Frontend store reducer indexes the last N `search_results` payloads by
   session.
4. `SearchCardsPanel` subscribes and renders them with `<a href target=_blank>`.

### 5.4 Component sketch

```tsx
// frontend/src/components/chat/SearchCardsPanel.tsx
export function SearchCardsPanel({ sessionId }: { sessionId: string }) {
  const cards = useStore((s) => selectLatestSearchCards(s, sessionId));
  if (!cards.length) return null;
  return (
    <aside className="w-[340px] border-l border-border/60 overflow-y-auto">
      <header className="px-4 py-2 text-xs text-muted-foreground">Sources</header>
      <ul className="divide-y divide-border/40">
        {cards.map((c) => (
          <li key={c.url} className="px-4 py-3">
            <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <Favicon url={c.url} /> <span>{c.ago}</span>
            </div>
            <a href={c.url} target="_blank" rel="noreferrer"
               className="block mt-1 text-sm text-primary hover:underline line-clamp-2">
              {c.title}
            </a>
            <p className="mt-1 text-xs text-muted-foreground line-clamp-2">{c.snippet}</p>
          </li>
        ))}
      </ul>
    </aside>
  );
}
```

Mount it in `ChatPane.tsx` alongside `ArtifactCard.tsx` — both share the
right-rail slot.

### 5.5 Why not extend `ActivityBar`?

`ActivityBar` intentionally hides when status is not `running`
(`ActivityBar.tsx:17`). Cards must *persist* — they are the agent's reading list.
Separate component, separate lifecycle.

---

## 6. Word-document artifact

### 6.1 Why `.docx`, not markdown

Markdown is the current easy path (see `research_and_report/test_cases.json:9`).
The user-visible output of research in the real world is a Word document —
styled headings, a chart, hyperlinks, tables. Requiring `.docx` forces:

- the agent to write a real rendering script (not just string-template markdown)
- a verifiable binary artifact we can open and inspect
- use of `python-docx` which is a stable dependency to pin

### 6.2 Renderer script contract

The agent must write `results/lt1_briefing/render.py` with roughly this shape:

```python
from docx import Document
from docx.shared import Inches

doc = Document()
doc.add_heading("NVDA — Equity Research Briefing", level=0)

doc.add_heading("Executive Summary", level=1)
doc.add_paragraph(summary_text)

doc.add_heading("Price & Indicators", level=1)
doc.add_picture("results/lt1_briefing/nvda_chart.png", width=Inches(6.0))
# …one short paragraph of interpretation…

doc.add_heading("News & Catalysts", level=1)
for item in news_items:                              # from web_research payload
    p = doc.add_paragraph(style="List Bullet")
    _add_hyperlink(p, item["title"], item["url"])    # helper uses docx OXML

doc.add_heading("Risks", level=1)
# …

doc.add_heading("Sources", level=1)
for i, src in enumerate(sources, 1):
    p = doc.add_paragraph(f"{i}. ")
    _add_hyperlink(p, src["url"], src["url"])

doc.save("results/lt1_briefing/NVDA_briefing.docx")
```

The helper `_add_hyperlink` is a short OXML snippet we include in the skill's
`REFERENCE.md` so the agent is not forced to invent it. This is legitimate
scaffolding — we are testing research + synthesis, not whether the agent can
reinvent `python-docx` internals under time pressure.

### 6.3 Dependency

Add `python-docx` to the scenario's opt-in dependency group. The chart PNG comes
from the existing `generate_chart` tool in `stock_strategy/tools.py`, which
already writes PNGs.

---

## 7. Skill: enhance `stock_strategy` (recommended over a new skill)

We enhance the existing skill pack rather than adding a parallel one, because
the domain keywords, tool set, and `SKILL.md` workflow are already 80% right.

### 7.1 Changes to `core/src/skill_packs/stock_strategy/SKILL.md`

Add a new workflow mode at the top of *Workflow*:

```
0. **Briefing mode** — If the user asks to "brief me on <TICKER>" or
   "research <TICKER>" or "write a report on <TICKER>":
     a. Call `web_research(query="$TICKER earnings filings analyst news",
                           fetch_top=3)` ONCE.
     b. Call `fetch_market_data(symbol=$TICKER, period="6mo", interval="1d")`.
     c. Call `compute_indicator` for RSI(14), SMA(50), SMA(200).
     d. Call `generate_chart` (candlestick + overlays) → PNG at
        `results/lt1_briefing/<TICKER>_chart.png`.
     e. Write `results/lt1_briefing/render.py` using the template in
        `REFERENCE.md#docx-template`.
     f. Run `render.py` via `run_command`.
     g. Stop. The `.docx` is the final artifact.

   Rules: at most **3** total `web_research` calls per briefing. Never call
   `web_search` or `web_fetch` directly — `web_research` supersedes them.
```

Briefing mode gives the agent a numbered recipe, not a free exploration — which
is the whole point of packaging this as a skill: the user's prompt stays short,
the skill fills in the structure.

### 7.2 Changes to `core/src/skill_packs/stock_strategy/REFERENCE.md`

Add the `_add_hyperlink` helper snippet and a minimal `render.py` template block
the agent can copy verbatim. Keep it short — we want the agent to adapt it, not
paste it blindly.

### 7.3 Changes to `core/src/skill_packs/stock_strategy/skill.py`

No new tools owned by the skill. `web_research` is a *runtime* tool
(`ToolGroup.RUNTIME`), always visible, so the skill just references it in its
workflow. Update `keywords` to include `"brief"`, `"briefing"`, `"research"`,
`"report on"` so intent routing picks the skill up when the user asks for a
briefing.

---

## 8. Eval-harness wiring

### 8.1 Directory

```
core/src/scenarios/lt1_equity_briefing/
├── __init__.py
├── scenario.py            # thin subclass of Scenario, mirrors research_and_report/scenario.py:14-27
├── evaluator.py           # docx validation (see §8.3) + base checks
└── test_cases.json
```

Register in `core/src/scenarios/registry.py` next to the others.

### 8.2 Test case

```json
[
  {
    "id": "lt1_brief_nvda",
    "ability": "long_horizon_composition",
    "difficulty": "hard",
    "skill_packs": ["stock_strategy"],
    "input": "Brief me on NVDA.",
    "expected_tools": ["web_research", "fetch_market_data", "compute_indicator",
                       "generate_chart", "write_file", "run_command"],
    "forbidden_tools": ["rm", "web_fetch", "web_search"],
    "artifact_path": "results/lt1_briefing/NVDA_briefing.docx",
    "supporting_artifacts": [
      "results/lt1_briefing/render.py",
      "results/lt1_briefing/NVDA_chart.png"
    ],
    "docx_required_headings": ["Executive Summary", "Price & Indicators",
                               "News & Catalysts", "Risks", "Sources"],
    "min_inline_images": 1,
    "min_hyperlinks": 5,
    "max_web_research_calls": 3,
    "max_steps": 30,
    "budget_usd": 1.50,
    "timeout_sec": 300,
    "description": "LT1: equity briefing as a Word doc, using the combined web_research tool and the stock_strategy skill."
  }
]
```

`forbidden_tools` includes the raw `web_search` / `web_fetch` — the scenario
explicitly grades whether the agent routed through the combined tool.

### 8.3 Evaluator extensions

New checks in `evaluator.py` (reuse the base evaluator from
`scenarios/research_and_report/evaluator.py` for G4/G5, add these):

```python
from docx import Document

def _grade_docx(path, tc):
    d = Document(path)                                       # G1: opens
    headings = [p.text for p in d.paragraphs if p.style.name.startswith("Heading")]
    missing = [h for h in tc["docx_required_headings"] if h not in headings]
    assert not missing, f"missing headings: {missing}"       # G2
    assert len(d.inline_shapes) >= tc["min_inline_images"]   # G3
    links = _count_hyperlinks(d)
    assert links >= tc["min_hyperlinks"]                     # G4
```

G7 (≤ 3 `web_research` calls) is a count over `trace.tool_calls`.

### 8.4 How to run

Mock (CI, no cost):

```bash
cd core
APEX_MOCK_LLM=1 uv run python -m eval.runner \
    --scenario lt1_equity_briefing \
    --cases lt1_brief_nvda
```

Live:

```bash
cd core
uv run python -m eval.runner \
    --scenario lt1_equity_briefing \
    --models claude-opus-4-7 \
    --cases lt1_brief_nvda \
    --strategies truncate \
    --timeout 300 \
    --output results/lt1
```

Interactive / TUI sanity run: launch the TUI, type `Brief me on NVDA.`, watch
the sidebar cards appear as `web_research` returns, and confirm the `.docx`
pops out of `results/lt1_briefing/`.

Mid-run-kill variant: use the existing LT1 kill hook in
`eval/runner.py:59-80` — the scenario should survive a kill between the
`web_research` call and the `render.py` run, because all intermediate state is
on disk (chart PNG, dumped JSON of news items).

---

## 9. Verification playbook

This is the sequence that proves the scenario works. Run it in order — each
step is a gate for the next.

### Step 1 — Unit-level: the new tool works in isolation

```bash
cd core
uv run pytest tests/tools/test_web_research.py -v
```

Pass criteria:
- All four cases in §4.5 pass.
- No unit test calls the old `web_search` / `web_fetch` directly — they are
  exercised only as dependencies of `web_research`.

### Step 2 — Mock-mode scenario run (no network, no API cost)

```bash
cd core
APEX_MOCK_LLM=1 uv run python -m eval.runner \
    --scenario lt1_equity_briefing \
    --cases lt1_brief_nvda
```

Pass criteria:
- Runner exits 0.
- `results/lt1/<run_id>/NVDA_briefing.docx` exists and opens with
  `python -c "from docx import Document; Document('…docx')"`.
- `results/lt1/<run_id>/trace.json` shows **zero** calls to `web_search` or
  `web_fetch` (forbidden) and **≤ 3** calls to `web_research`.
- The evaluator's G1–G7 all pass; the summary row in the Rich table is green.

### Step 3 — Single live run on one model

```bash
cd core
uv run python -m eval.runner \
    --scenario lt1_equity_briefing \
    --models claude-opus-4-7 \
    --cases lt1_brief_nvda \
    --strategies truncate \
    --timeout 300 \
    --output results/lt1_live
```

Pass criteria:
- Wall-clock between 90 s and 300 s (faster than 90 s usually means the model
  shortcut something; slower than 300 s means the timeout killed the run).
- `trace.json` shows tool diversity ≥ 4 and at least one "compositional hop"
  as defined in §0.
- Cost ≤ `budget_usd` (currently $1.50).

### Step 4 — Open the `.docx` by hand and eyeball it

```bash
open results/lt1_live/<run_id>/NVDA_briefing.docx
```

Pass criteria:
- Five Word headings are present **and styled as Word headings** (not just
  bold text).
- *Price & Indicators* shows an actual inline candlestick chart, not a broken
  image icon.
- *News & Catalysts* bullets are clickable hyperlinks.
- *Sources* contains ≥ 5 links. Click two at random — they load a real page.

If any of these fail, the automated evaluator missed something and needs a new
assertion.

### Step 5 — UI: the sidebar cards render and persist

1. `cd frontend && pnpm dev`
2. Start a session, type `Brief me on NVDA.`
3. As soon as `web_research` completes (single event), the
   `SearchCardsPanel` should populate with up-to-`num_results` cards —
   favicon, ago-timestamp, title (clickable), one-line snippet.
4. **After** the run completes, the cards must still be visible (this is the
   difference from `ActivityBar`, which hides on idle).
5. Click one card → opens in a new tab.

Pass criteria: cards appear within 500 ms of the tool completing; cards
persist after session status transitions to `completed`; zero console errors.

### Step 6 — Mid-run-kill recovery (the LT1 tier's reason for existing)

```bash
cd core
uv run python -m eval.runner \
    --scenario lt1_equity_briefing \
    --cases lt1_brief_nvda \
    --strategies truncate \
    --kill-at 0.5                # existing LT1 hook in eval/runner.py:59-80
```

Pass criteria:
- The runner kills the process roughly halfway through (after `web_research`
  returned, typically before `render.py` runs).
- On resume, the agent reads the intermediate JSON news dump + chart PNG from
  disk instead of re-searching.
- Final `.docx` is produced and passes G1–G4.
- Total `web_research` calls across the two halves is still ≤ 3 (G7).

### Step 7 — Establish a regression baseline

```bash
cd core
uv run python -m eval.runner \
    --scenario lt1_equity_briefing \
    --models claude-opus-4-7 \
    --cases lt1_brief_nvda \
    --output results/lt1_baseline \
    --update-baseline --baseline results/lt1_baseline/baseline.json
```

Commit `baseline.json`. Future PRs run with `--baseline results/lt1_baseline/baseline.json`
and the comparator (`core/src/eval/comparator.py:149+`) blocks regressions on
pass-rate, wall-clock, cost, and tool-call counts.

### What "verified" means, concretely

The scenario is verified when, on a clean checkout:

1. Steps 1–2 pass in CI (mock path).
2. Step 3 passes on at least one live model (`claude-opus-4-7` is the
   reference).
3. Step 4 passes a human eyeball check for one ticker.
4. Step 5 passes a manual UI smoke test.
5. Step 6 passes — this is the one that actually distinguishes "long task" from
   "long-horizon task".
6. Step 7 produces a committed baseline so future drift is auto-caught.

Any one failure is a bug; don't paper over it with a relaxed threshold. If a
step keeps flaking because of external providers (Tavily/DuckDuckGo outages),
log it as *infrastructure skip*, not *agent regression* — same rule as §12.

---

## 10. Build order (suggested)

1. **`web_research` tool + unit tests.** Isolated, lands without touching UI
   or skills. Merge first.
2. **Skill workflow update.** Add briefing-mode recipe + `REFERENCE.md` docx
   template. Shippable independent of UI.
3. **Scenario + evaluator + test case.** Runs in mock mode as soon as (1) and
   (2) are in.
4. **Sidebar `SearchCardsPanel`.** Purely additive UI; can land in parallel
   with (3).
5. **First live run on a single model, one ticker.** Establish the baseline
   for `--baseline` gating.

Each step is independently reviewable and reversible. No step requires the
others to be perfect to demonstrate progress.

## 11. Open questions

- `.docx` vs `.pdf`. `.docx` is strictly easier to grade programmatically and
  matches the user's "Word doc well formatted" ask. If we later need PDF, add
  a second renderer behind a flag.
- Favicon service for the sidebar cards. Default to
  `https://www.google.com/s2/favicons?domain=…` for v1; self-host later if it
  becomes a privacy issue.
- Whether `web_research` should also index fetched pages into the RAG store on
  the fly. Out of scope for v1 — keep the tool stateless; a follow-up
  `rag_index_from_research` tool can consume its output.

## 12. See also

- `doc/eval-suite.md` — tier definitions, grading metrics.
- `doc/design-spec.md` — runtime architecture this plugs into.
- `core/src/scenarios/research_and_report/` — the easier filesystem-only
  baseline this scenario builds on.
- `core/src/skill_packs/stock_strategy/SKILL.md` — skill that gets the
  briefing-mode workflow.
