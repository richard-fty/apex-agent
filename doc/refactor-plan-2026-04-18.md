# Apex Agent Refactor Plan

Date: 2026-04-18
Status: Draft for review

This plan covers three things:

1. clarifying the `core/src/*` package layout
2. tightening design-spec alignment where the implementation is weaker than the docs claim
3. cleaning up the web implementation so it matches the stated platform plan more closely

The goal is to reduce confusion and architectural drift without forcing a risky repo-wide rewrite.

## 1. Summary

The current repo is directionally strong:

- the managed-agent core shape is present
- the web stack exists and is usable
- the evented UI model is real

The biggest problems are structural clarity and contract drift:

- the package boundary should live under `core/src/`
- some docs describe logical paths that no longer match the filesystem
- the web SSE/replay behavior does not fully match the plan
- several modules are broader than their intended responsibility

## 2. Recommended Direction

Do not rename the inner Python import package `agent` first.

Instead:

- rename the outer workspace member to `core/`
- keep the import package name `agent`
- optionally move to a `src/` layout inside that member in a second step

This gives the repo a cleaner physical structure without breaking every `from agent...` import.

Recommended target shape:

```text
pyproject.toml
core/
  pyproject.toml
  src/
    agent/
    tools/
    services/
    scenarios/
    skill_packs/
    eval/
  tests/
backend/
frontend/
tui/
doc/
```

## 3. Why This Layout

This approach is safer than renaming the import package because:

- imports remain stable
- backend and TUI package dependencies stay mostly unchanged
- packaging intent becomes obvious
- the importable code is isolated under a standard `src/` root

This also makes the monorepo boundary clearer:

- root `pyproject.toml` stays the workspace definition
- `core/pyproject.toml` stays the distributable package definition
- `backend/` and `tui/` continue to depend on the core package

## 4. Refactor Phases

### Phase 1: Documentation and Naming Cleanup

Scope:

- rename outer workspace member directory to `core/`
- update workspace membership in the root `pyproject.toml`
- update package-member paths in docs and contributor guidance
- update any tooling, test paths, and Makefile references

Expected benefit:

- immediate readability improvement
- less onboarding confusion
- lower chance of path mistakes in future docs and scripts

Risk:

- low to medium
- mostly path/config churn

Review gate:

- workspace installs successfully
- tests discover the same suites as before
- no import-path rewrite required

### Phase 2: Optional `src/` Layout for the Core Member

Scope:

- move package code under `core/src/`
- leave tests at `core/tests/`
- update build configuration accordingly

Expected benefit:

- clearer packaging boundary
- fewer accidental local-import/path issues
- cleaner long-term structure

Risk:

- medium
- packaging/test config must be updated carefully

Review gate:

- editable installs work
- backend imports still resolve
- test discovery still works

### Phase 3: Web Contract Alignment

Scope:

- align SSE lifecycle with the documented contract
- make replay come from durable session storage, not only the in-memory bus
- decide whether `stream_end` should close the stream or simply mark turn completion
- implement artifact auto-open behavior if it remains a product requirement

Expected benefit:

- code matches the web plan more closely
- reconnect behavior becomes more robust
- fewer race-condition edge cases

Risk:

- medium to high
- touches live session behavior

Review gate:

- reconnect replay works after process restarts
- SSE semantics are documented and tested
- frontend state remains event-derived and deterministic

### Phase 4: Route and Runtime Responsibility Cleanup

Scope:

- split `sessions_routes.py` into focused route modules
- reduce broad modules where they mix CRUD, turn execution, approvals, SSE, and artifacts
- tighten runtime module boundaries where the harness shape is currently too spread out

Expected benefit:

- easier reasoning about ownership
- easier testing
- less architectural drift versus the design spec

Risk:

- medium
- mostly internal movement and interface cleanup

Review gate:

- external HTTP API remains unchanged
- route responsibilities become easier to audit
- runtime internals remain compatible with the current event model

## 5. Design-Spec Evaluation

### Strong Alignment

- session/event-driven architecture is present
- tool boundary is explicit
- approval flow is runtime-mediated
- sandbox abstraction exists
- frontends act as consumers over emitted runtime events

These are the parts of the design that look fundamentally sound.

### Partial Alignment

- web replay durability is weaker than the plan implies
- SSE lifecycle semantics are not fully settled
- some “shipped” claims in docs are stronger than the available proof
- route/module boundaries are broader than the intended architecture

These are not signs of a broken architecture. They are signs of an MVP that has outgrown some of its early shortcuts.

### Weakest Areas

- documentation path accuracy
- web reconnection contract
- in-process assumptions in the current server runner model
- over-centralized route modules

## 6. Recommended Cleanup Items

Priority 1:

- rename outer workspace member
- update docs to distinguish logical architecture paths from actual filesystem paths
- remove path ambiguity in README and design docs

Priority 2:

- split session, turn, approval, SSE, and artifact routes into separate modules
- define one authoritative SSE contract and update code/docs together
- implement durable replay via session storage

Priority 3:

- adopt `src/` layout for the core package member
- reduce runtime module sprawl
- review “shipped” claims in docs against actual tests and CI wiring

## 7. Proposed Decisions For Review

Decision 1:

- rename outer workspace member to `core/`

Decision 2:

- keep import package name `agent`

Decision 3:

- defer `src/` layout until after the outer-folder rename lands cleanly

Decision 4:

- treat SSE durable replay as a required architecture fix, not a nice-to-have

Decision 5:

- split route responsibilities before adding more web features

## 8. Suggested Execution Order

1. Rename outer workspace member and fix workspace/test/build references.
2. Update docs so path references are accurate and explicit.
3. Split server routes by responsibility without changing API behavior.
4. Fix SSE/replay semantics and add tests for reconnect behavior.
5. Consider `src/` layout once the package/member boundary is already clear.
6. Reassess the design docs and downgrade any claims that still overstate what is proven.

## 9. Non-Goals

- renaming every `from agent...` import immediately
- redesigning the whole runtime before fixing obvious structural confusion
- changing the public HTTP API during cleanup
- introducing distributed infra before the local contracts are solid

## 10. Review Questions

- Is `core/` the preferred replacement name, or should it be `apex_core/`?
- Do we want to preserve the current SSE behavior and update the plan, or change the code to match the plan?
- Should the `src/` migration happen immediately after the rename, or only after web-contract cleanup?
- Which matters more in the next cycle: layout clarity or web durability?
