import { create } from "zustand";
import type {
  AgentEvent,
  ApprovalRequest,
  Artifact,
  PlanKind,
  PlanStep,
  SearchResultCard,
  TokenUsage,
  TurnSummary,
  User,
} from "./types";

/**
 * ChatItem — a typed union of things that can appear in the chat stream.
 *
 * User turn, assistant text (streaming or final), an inline tool-call chip,
 * and an inline artifact card. Rendered chronologically so the user sees
 * exactly what the agent did between messages.
 */
export type ChatItem =
  | { kind: "user"; text: string; turnIndex: number; turnId?: string | null }
  | { kind: "assistant"; content: string; streaming: boolean; turnIndex: number }
  | { kind: "tool"; toolCallId: string; turnIndex: number }
  | { kind: "artifact"; artifactId: string; turnIndex: number };

export interface ToolCallRecord {
  id: string;
  step: number;
  name: string;
  arguments: Record<string, unknown>;
  status: "running" | "completed" | "failed" | "denied";
  duration_ms?: number;
  content?: string;
  reason?: string;
  search_results?: SearchResultCard[];
}

/** Per-session state. Event-derived only — UI state lives in the top-level
 * `ui` bag so replaying events doesn't stomp user choices. */
export interface SessionState {
  items: ChatItem[];
  seenSeqs: Record<number, true>;
  toolCalls: Record<string, ToolCallRecord>;
  artifacts: Record<string, Artifact>;
  artifactOrder: string[];
  pendingArtifactIds: string[];
  loadedSkills: string[];
  disclaimer: string | null;
  workflowPlan: PlanStep[];
  workflowSkillName: string | null;
  plan: PlanStep[];
  planKind: PlanKind;
  pending: ApprovalRequest | null;
  usage: TokenUsage;
  status: "idle" | "running" | "waiting_approval" | "completed" | "failed";
  turnIndex: number;
}

const emptySession = (): SessionState => ({
  items: [],
  seenSeqs: {},
  toolCalls: {},
  artifacts: {},
  artifactOrder: [],
  pendingArtifactIds: [],
  loadedSkills: [],
  disclaimer: null,
  workflowPlan: [],
  workflowSkillName: null,
  plan: [],
  planKind: "task",
  pending: null,
  usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, cost_usd: 0 },
  status: "idle",
  turnIndex: 0,
});

/** UI state for the artifact/tool side panel. */
export type PanelMode =
  | { kind: "closed" }
  | { kind: "artifact"; artifactId: string }
  | { kind: "tool"; toolCallId: string }
  | { kind: "history" }
  | { kind: "social"; url: string };

interface State {
  user: User | null;
  setUser: (u: User | null) => void;

  sessions: Record<string, SessionState>;
  turnsBySession: Record<string, TurnSummary[]>;
  activeSessionId: string | null;
  setActiveSessionId: (id: string | null) => void;

  setTurns: (sessionId: string, turns: TurnSummary[]) => void;
  replaceSessionEvents: (sessionId: string, events: AgentEvent[]) => void;
  ingest: (sessionId: string, ev: AgentEvent) => void;
  resetSession: (sessionId: string) => void;

  ui: {
    panel: PanelMode;
    artifactView: "preview" | "source";
    toolView: "result" | "arguments";
    panelWidthPct: number;
  };
  openArtifact: (id: string) => void;
  openTool: (id: string) => void;
  openHistory: () => void;
  openSocial: (url: string) => void;
  closePanel: () => void;
  setArtifactView: (v: "preview" | "source") => void;
  setToolView: (v: "result" | "arguments") => void;
}

const toolCallId = (ev: { tool_call_id?: string | null; step: number; name: string }) =>
  ev.tool_call_id || `${ev.step}:${ev.name}`;

const hiddenChatTools = new Set([
  "load_skill",
  "todo_write",
  "todo_update",
  "todo_view",
  "update_plan",
]);

function shouldRenderToolChip(name: string) {
  return !hiddenChatTools.has(name);
}

function updateWorkflowPlanForTool(
  steps: PlanStep[],
  toolName: string,
  status: PlanStep["status"],
) {
  if (steps.length === 0) return steps;
  const toolToken = toolName.toLowerCase();
  let matched = false;
  const next = steps.map((step, index) => {
    const text = step.text.toLowerCase();
    if (text.includes(toolToken)) {
      matched = true;
      return { ...step, status };
    }
    if (toolName === "fetch_market_data" && index === 0 && step.status === "pending") {
      return { ...step, status: "completed" as const };
    }
    return step;
  });
  return matched ? next : steps;
}

function prettySkillName(name: string): string {
  return name
    .split(/[_-]/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function insertBeforeStreamingAssistant(
  items: ChatItem[],
  item: ChatItem,
  turnIndex: number,
) {
  const index = items.findIndex(
    (existing) =>
      existing.kind === "assistant" &&
      existing.streaming &&
      existing.turnIndex === turnIndex,
  );
  if (index === -1) {
    items.push(item);
    return;
  }
  items.splice(index, 0, item);
}

function appendArtifactItemOnce(items: ChatItem[], artifactId: string, turnIndex: number) {
  if (items.some((item) => item.kind === "artifact" && item.artifactId === artifactId)) {
    return;
  }
  items.push({ kind: "artifact", artifactId, turnIndex });
}

function flushPendingArtifacts(st: SessionState, turnIndex: number) {
  for (const artifactId of st.pendingArtifactIds) {
    appendArtifactItemOnce(st.items, artifactId, turnIndex);
  }
  st.pendingArtifactIds = [];
}

export const useStore = create<State>()((set, get) => ({
  user: null,
  setUser: (u) => set({ user: u }),

  sessions: {},
  turnsBySession: {},
  activeSessionId: null,
  setActiveSessionId: (id) => set({ activeSessionId: id }),

  setTurns: (sid, turns) =>
    set((s) => ({
      turnsBySession: {
        ...s.turnsBySession,
        [sid]: [...turns].sort((a, b) => a.started_seq - b.started_seq),
      },
    })),

  replaceSessionEvents: (sid, events) => {
    set((s) => ({
      sessions: { ...s.sessions, [sid]: emptySession() },
      turnsBySession: { ...s.turnsBySession, [sid]: [] },
    }));
    for (const ev of [...events].sort((a, b) => a.seq - b.seq)) {
      get().ingest(sid, ev);
    }
  },

  resetSession: (sid) =>
    set((s) => ({
      sessions: { ...s.sessions, [sid]: emptySession() },
      turnsBySession: { ...s.turnsBySession, [sid]: [] },
    })),

  ingest: (sid, ev) => {
    const sessions = { ...get().sessions };
    const st = { ...(sessions[sid] ?? emptySession()) };
    const turnsBySession = { ...get().turnsBySession };
    const turnList = [...(turnsBySession[sid] ?? [])];
    st.items = [...st.items];
    if (ev.seq > 0 && st.seenSeqs[ev.seq]) return;
    st.seenSeqs = { ...st.seenSeqs };
    st.toolCalls = { ...st.toolCalls };
    st.artifacts = { ...st.artifacts };
    st.pendingArtifactIds = [...st.pendingArtifactIds];
    st.workflowPlan = [...st.workflowPlan];
    st.plan = [...st.plan];

    const ti = st.turnIndex;

    switch (ev.type) {
      case "turn_started":
        st.turnIndex += 1;
        st.items.push({
          kind: "user",
          text: ev.user_input,
          turnIndex: st.turnIndex,
          turnId: ev.turn_id,
        });
        st.items.push({ kind: "assistant", content: "", streaming: true, turnIndex: st.turnIndex });
        st.status = "running";
        st.pending = null;
        st.pendingArtifactIds = [];
        st.workflowPlan = [];
        st.workflowSkillName = null;
        if (ev.turn_id && !turnList.some((turn) => turn.turn_id === ev.turn_id)) {
          turnList.push({
            turn_id: ev.turn_id,
            started_at: ev.timestamp,
            started_seq: ev.seq,
            ended_at: null,
            ended_seq: null,
            status: "running",
            user_preview: ev.user_input,
            assistant_preview: "",
          });
        }
        break;

      case "assistant_token": {
        // Append to the current streaming assistant item. After replay, there
        // may be no active placeholder because a prior assistant_note finalized
        // it; in that case create a new tail item so continued output does not
        // attach above earlier tool/note rows.
        let appended = false;
        for (let i = st.items.length - 1; i >= 0; i--) {
          const it = st.items[i];
          if (it.kind === "assistant" && it.streaming && it.turnIndex === st.turnIndex) {
            st.items[i] = { ...it, content: it.content + ev.text };
            appended = true;
            break;
          }
        }
        if (!appended) {
          st.items.push({
            kind: "assistant",
            content: ev.text,
            streaming: true,
            turnIndex: st.turnIndex,
          });
        }
        break;
      }

      case "assistant_snapshot": {
        let replaced = false;
        for (let i = st.items.length - 1; i >= 0; i--) {
          const it = st.items[i];
          if (it.kind === "assistant" && it.streaming && it.turnIndex === st.turnIndex) {
            st.items[i] = { ...it, content: ev.content };
            replaced = true;
            break;
          }
        }
        if (!replaced) {
          st.items.push({
            kind: "assistant",
            content: ev.content,
            streaming: true,
            turnIndex: st.turnIndex,
          });
        }
        break;
      }

      case "assistant_message": {
        let updated = false;
        for (let i = st.items.length - 1; i >= 0; i--) {
          const it = st.items[i];
          if (it.kind === "assistant" && it.turnIndex === st.turnIndex) {
            st.items[i] = { ...it, content: ev.content || it.content, streaming: false };
            updated = true;
            break;
          }
        }
        if (!updated && ev.content?.trim()) {
          st.items.push({
            kind: "assistant",
            content: ev.content,
            streaming: false,
            turnIndex: st.turnIndex,
          });
        }
        flushPendingArtifacts(st, st.turnIndex);
        if (ev.turn_id) {
          const idx = turnList.findIndex((turn) => turn.turn_id === ev.turn_id);
          if (idx !== -1) {
            turnList[idx] = {
              ...turnList[idx],
              assistant_preview: ev.content,
            };
          }
        }
        break;
      }

      case "assistant_note": {
        // The runtime emits assistant_note containing the SAME full text it
        // just streamed via assistant_token events (before calling a tool).
        // Dedupe: if replay only rebuilt an empty streaming placeholder, turn
        // that placeholder into the note instead of leaving it for future
        // tokens to attach to in the wrong position.
        let deduped = false;
        for (let i = st.items.length - 1; i >= 0; i--) {
          const it = st.items[i];
          if (it.kind !== "assistant") continue;
          if (
            it.turnIndex === st.turnIndex &&
            (it.streaming || it.content.trim() === ev.text.trim())
          ) {
            st.items[i] = { ...it, content: ev.text, streaming: false };
            deduped = true;
          }
          break; // only check the last assistant item
        }
        if (!deduped) {
          st.items.push({
            kind: "assistant", content: ev.text, streaming: false, turnIndex: ti,
          });
        }
        break;
      }

      case "education_disclaimer":
        st.disclaimer = ev.message;
        break;

      case "skill_auto_loaded":
        if (!st.loadedSkills.includes(ev.skill_name)) {
          st.loadedSkills = [...st.loadedSkills, ev.skill_name];
        }
        {
          const id = `skill:${ev.skill_name}:${ti}`;
          const alreadyShown = st.items.some(
            (item) => item.kind === "tool" && item.toolCallId === id,
          );
          st.toolCalls[id] = {
            id,
            step: 0,
            name: "load_skill",
            arguments: { name: ev.skill_name },
            status: "completed",
            content: `Skill loaded: ${prettySkillName(ev.skill_name)}`,
          };
          if (!alreadyShown) {
            insertBeforeStreamingAssistant(st.items, { kind: "tool", toolCallId: id, turnIndex: ti }, ti);
          }
        }
        break;

      case "turn_finished": {
        let updated = false;
        for (let i = st.items.length - 1; i >= 0; i--) {
          const it = st.items[i];
          if (it.kind === "assistant" && it.streaming && it.turnIndex === ti) {
            st.items[i] = { ...it, content: ev.content || it.content, streaming: false };
            updated = true;
            break;
          }
        }
        if (!updated && ev.content?.trim()) {
          const sameTurnAssistant = st.items.some(
            (item) =>
              item.kind === "assistant" &&
              item.turnIndex === ti &&
              item.content.trim() === ev.content.trim(),
          );
          if (!sameTurnAssistant) {
            st.items.push({
              kind: "assistant",
              content: ev.content,
              streaming: false,
              turnIndex: ti,
            });
          }
        }
        flushPendingArtifacts(st, ti);
        break;
      }

      case "tool_started": {
        const id = toolCallId(ev);
        st.workflowPlan = updateWorkflowPlanForTool(st.workflowPlan, ev.name, "in_progress");
        st.toolCalls[id] = {
          id,
          step: ev.step,
          name: ev.name,
          arguments: ev.arguments,
          status: "running",
        };
        if (
          shouldRenderToolChip(ev.name) &&
          !st.items.some((item) => item.kind === "tool" && item.toolCallId === id)
        ) {
          st.items.push({ kind: "tool", toolCallId: id, turnIndex: ti });
        }
        break;
      }

      case "tool_finished": {
        const id = toolCallId(ev);
        const existing = st.toolCalls[id];
        st.workflowPlan = updateWorkflowPlanForTool(
          st.workflowPlan,
          ev.name,
          ev.success ? "completed" : "failed",
        );
        st.toolCalls[id] = {
          id,
          step: ev.step,
          name: ev.name,
          arguments: ev.arguments,
          status: ev.success ? "completed" : "failed",
          duration_ms: ev.duration_ms,
          content: ev.content,
          reason: existing?.reason,
          search_results: ev.search_results ?? existing?.search_results,
        };
        break;
      }

      case "tool_denied": {
        if (ev.tool_call_id && st.toolCalls[ev.tool_call_id]) {
          const tc = st.toolCalls[ev.tool_call_id];
          st.toolCalls[ev.tool_call_id] = { ...tc, status: "denied", reason: ev.reason };
          break;
        }
        // Older denied events have no tool_call_id; attach to the most recent
        // running call with the same name as a best-effort match.
        for (const [id, tc] of Object.entries(st.toolCalls)) {
          if (tc.name === ev.name && tc.status === "running") {
            st.toolCalls[id] = { ...tc, status: "denied", reason: ev.reason };
            break;
          }
        }
        break;
      }

      case "approval_requested":
        st.status = "waiting_approval";
        st.pending = { tool_name: ev.tool_name, reason: ev.reason, step: ev.step };
        break;

      case "approval_resolved":
        st.pending = null;
        st.status = "running";
        break;

      case "error":
        st.items.push({
          kind: "assistant", content: `⚠ ${ev.message}`, streaming: false, turnIndex: ti,
        });
        break;

      case "stream_end": {
        st.status =
          ev.final_state === "waiting_approval"
            ? "waiting_approval"
            : (ev.final_state as SessionState["status"]);
        if (ev.turn_id) {
          const idx = turnList.findIndex((turn) => turn.turn_id === ev.turn_id);
          if (idx !== -1) {
            turnList[idx] = {
              ...turnList[idx],
              ended_at: ev.timestamp,
              ended_seq: ev.seq > 0 ? ev.seq : turnList[idx].ended_seq,
              status: ev.final_state,
            };
          }
        }
        // Unflag any still-streaming item.
        for (let i = st.items.length - 1; i >= 0; i--) {
          const it = st.items[i];
          if (it.kind === "assistant" && it.streaming) {
            st.items[i] = { ...it, streaming: false };
            break;
          }
        }
        break;
      }

      case "usage":
        st.usage = {
          prompt_tokens: st.usage.prompt_tokens + ev.usage.prompt_tokens,
          completion_tokens: st.usage.completion_tokens + ev.usage.completion_tokens,
          total_tokens: st.usage.total_tokens + ev.usage.total_tokens,
          cost_usd: st.usage.cost_usd + ev.usage.cost_usd,
        };
        break;

      case "workflow_plan_updated":
        st.workflowPlan = ev.steps;
        st.workflowSkillName = ev.skill_name;
        break;

      case "plan_updated":
        st.plan = ev.steps;
        st.planKind = ev.kind ?? "task";
        break;

      case "artifact_created":
        st.artifacts[ev.artifact_id] = {
          id: ev.artifact_id,
          kind: ev.kind,
          name: ev.name,
          language: ev.language,
          mime: ev.mime,
          description: ev.description,
          content: "",
          finalized: false,
          size: null,
        };
        if (!st.artifactOrder.includes(ev.artifact_id)) {
          st.artifactOrder = [...st.artifactOrder, ev.artifact_id];
        }
        if (st.status === "running") {
          if (!st.pendingArtifactIds.includes(ev.artifact_id)) {
            st.pendingArtifactIds = [...st.pendingArtifactIds, ev.artifact_id];
          }
        } else {
          appendArtifactItemOnce(st.items, ev.artifact_id, ti);
        }
        break;

      case "artifact_patch": {
        const a = st.artifacts[ev.artifact_id];
        if (!a) break;
        const next = { ...a };
        next.content = ev.op === "append" ? a.content + (ev.text ?? "") : ev.content ?? "";
        st.artifacts[ev.artifact_id] = next;
        break;
      }

      case "artifact_finalized": {
        const a = st.artifacts[ev.artifact_id];
        if (!a) break;
        st.artifacts[ev.artifact_id] = { ...a, finalized: true, size: ev.size };
        break;
      }

      default:
        break;
    }

    if (ev.seq > 0) st.seenSeqs[ev.seq] = true;
    sessions[sid] = st;
    turnsBySession[sid] = turnList.sort((a, b) => a.started_seq - b.started_seq);
    set({ sessions, turnsBySession });
  },

  ui: {
    panel: { kind: "closed" },
    artifactView: "preview",
    toolView: "result",
    panelWidthPct: 55,
  },
  openArtifact: (id) =>
    set((s) => ({
      ui: { ...s.ui, panel: { kind: "artifact", artifactId: id } },
    })),
  openTool: (id) =>
    set((s) => ({
      ui: { ...s.ui, panel: { kind: "tool", toolCallId: id } },
    })),
  openHistory: () =>
    set((s) => ({
      ui: { ...s.ui, panel: { kind: "history" } },
    })),
  openSocial: (url) =>
    set((s) => ({
      ui: { ...s.ui, panel: { kind: "social", url } },
    })),
  closePanel: () => set((s) => ({ ui: { ...s.ui, panel: { kind: "closed" } } })),
  setArtifactView: (v) => set((s) => ({ ui: { ...s.ui, artifactView: v } })),
  setToolView: (v) => set((s) => ({ ui: { ...s.ui, toolView: v } })),
}));
