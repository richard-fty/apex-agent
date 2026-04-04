# Relay Design Checklist

Use this checklist when designing or reviewing new features for `relay`.

The goal is not to mimic Claude Code's file structure. The goal is to apply the stable design principles behind strong agent runtimes.

## Core Principle

- Prefer runtime design over prompt-only behavior.
- Prefer explicit control paths over hidden heuristics.
- Prefer composable execution over one large loop.
- Prefer fail-closed defaults for risky actions.
- Prefer dynamic tool visibility over exposing every tool all the time.

## 1. Runtime First

Ask:

- Is this behavior enforced by runtime code, not only by prompt instructions?
- If the model ignores a prompt suggestion, does the system still behave safely?
- Is the important decision made by a policy, orchestrator, or executor instead of a loose skill workflow?

Good signs:

- retrieval is injected by runtime
- approvals pause execution in runtime
- tool visibility is assembled by runtime
- context is prepared by runtime

Red flags:

- "the model should remember to do this"
- "the skill tells it to follow this workflow"
- "we hope the prompt is strong enough"

## 2. Tool Boundary

Ask:

- Is every real capability represented as a tool or runtime service?
- Is the boundary between read, write, execute, network, and memory actions explicit?
- Can you tell what the agent is allowed to do by inspecting the tool surface?

Good signs:

- tools define capability boundaries
- runtime services sit behind tool entrypoints
- no hidden side effects outside the tool/runtime path

Red flags:

- the model can trigger behavior not represented in the tool system
- business logic is embedded directly in prompt templates

## 3. Tool Metadata

Ask:

- Does each tool carry runtime behavior metadata?
- Can policy decisions be made from tool metadata instead of tool-name special cases?

Minimum metadata:

- `is_read_only`
- `is_concurrency_safe`
- `requires_confirmation`
- `is_networked`
- `mutates_state`
- `is_destructive`
- `tool_group`
- `loading_strategy`

Good signs:

- access control reads tool metadata
- tool surfacing uses tool metadata
- high-risk tools are easy to identify

## 4. Dynamic Tool Visibility

Ask:

- Are only relevant tools exposed to the model for the current turn?
- Are write/admin tools hidden until needed?
- Are retrieval and memory tools treated differently from core tools?

Good signs:

- core tools are usually visible
- skill tools appear when skills are loaded
- retrieval tools are conditionally surfaced
- runtime-injected tools appear only for specific intents

Red flags:

- every tool is always exposed
- the model must understand internal architecture to use the system well

## 5. Two-Layer Execution

Ask:

- Is session-level orchestration separate from turn-level execution?
- Can conversation state evolve without bloating the turn loop?
- Can a single turn be paused, resumed, retried, or replayed cleanly?

Recommended separation:

- session/state layer
  - messages
  - loaded skills
  - retrieval state
  - approval state
  - usage/cost

- turn execution layer
  - model call
  - tool call parsing
  - tool execution
  - recovery
  - continue/stop decision

Red flags:

- one giant loop owns everything
- pause/resume is difficult to add
- approval logic is mixed directly into UI code

## 6. Context Engineering

Ask:

- Is context assembled intentionally instead of just appended forever?
- Are retrieval results summarized before injection?
- Are old turns compressed in layers instead of only truncated?

Prefer:

- system instructions
- loaded skill context
- retrieval context
- compressed history
- recent turns

Good signs:

- tool results can be summarized
- retrieval context is injected separately
- context overflow has a recovery path

Red flags:

- raw results are dumped directly into history
- retrieval chunks are appended without filtering
- context management is only "truncate older messages"

## 7. Retrieval As Runtime

Ask:

- Is retrieval treated as an internal runtime capability rather than a user-facing concept?
- Can the system perform local-first retrieval automatically?
- Are indexing and retrieval separated by risk level?

Good signs:

- users ask for outcomes, not "RAG"
- local retrieval happens when relevant
- `rag_query` is low-risk and read-oriented
- `rag_index` is controlled and approval-gated

Red flags:

- users must understand "RAG" to use the product
- indexing is always visible
- retrieval is just another random tool with no policy around it

## 8. Human In The Loop

Ask:

- Can the system return `allow`, `ask`, or `deny` for an action?
- Does `ask` pause execution instead of crashing the run?
- Can the user approve once or create a session-scoped rule?

Good signs:

- resumable approval
- pending approval state
- approve once / approve session / deny / deny session
- permission modes

Permission mode examples:

- `plan`
- `default`
- `accept_edits`
- `auto`
- `dont_ask`

Red flags:

- approval is implemented as ad hoc UI prompt logic
- denied actions force the whole run to fail
- one approval gets over-generalized forever

## 9. Fail-Closed Defaults

Ask:

- If the system is uncertain, does it choose the safer behavior?
- Are write-like or networked operations conservative by default?
- Is concurrency opt-in rather than assumed?

Good signs:

- risky actions require confirmation
- unknown actions do not silently pass
- runtime-injected tools are hidden by default

Red flags:

- convenience overrides safety by default
- broad auto-approval without scope

## 10. Recovery Paths

Ask:

- What happens if a tool call is malformed?
- What happens if a tool result is too large?
- What happens if context overflows?
- What happens after repeated tool failure?

Minimum recovery paths:

- argument parse failure -> retry hint
- oversized result -> summarize or compact
- context overflow -> compress and retry
- repeated failure -> structured stop reason

Red flags:

- runtime mostly assumes happy path
- one tool failure derails the whole run without explanation

## 11. Composability

Ask:

- Can the same execution core later power subagents, research mode, verification, or background tasks?
- Are services reusable without copying loop logic?
- Is the runtime flexible enough to support different frontends?

Good signs:

- shared session engine
- shared turn executor
- shared policy modules
- frontend-specific code stays thin

Red flags:

- CLI, TUI, and benchmark each implement their own runtime behavior
- adding a subagent would require copying the loop

## 12. Product-Layer Simplicity

Ask:

- Does the user need to understand internal implementation details?
- Are internal terms like "RAG", "embedding", or "tool metadata" hidden from normal usage?
- Does the system speak in user intent, not internal mechanism?

Good signs:

- "search my saved knowledge"
- "add this folder to future reference"
- "I need approval before doing this"

Red flags:

- "please call rag_query"
- "index this into vector storage"
- "the user must know the runtime architecture"

## Review Questions

Before merging a new feature, ask:

1. Is this runtime-first or prompt-first?
2. Does it strengthen or blur capability boundaries?
3. Does it improve or weaken fail-closed behavior?
4. Does it make tool visibility clearer or noisier?
5. Does it keep the user focused on intent instead of implementation?
6. Does it make the execution core more composable?
7. Does it add a recovery path where one was missing?

## Rule Of Thumb

If a feature mostly depends on the model remembering instructions, it is probably under-engineered.

If a feature becomes safer, clearer, and more composable when moved into runtime, it probably belongs in runtime.
