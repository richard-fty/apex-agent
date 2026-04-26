import { create } from "zustand";
import type {
  AgentEvent,
  ApprovalRequest,
  Artifact,
  PlanStep,
  SearchResultCard,
  TokenUsage,
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
  | { kind: "user"; text: string; turnIndex: number }
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
  toolCalls: Record<string, ToolCallRecord>;
  artifacts: Record<string, Artifact>;
  artifactOrder: string[];
  loadedSkills: string[];
  disclaimer: string | null;
  plan: PlanStep[];
  pending: ApprovalRequest | null;
  usage: TokenUsage;
  status: "idle" | "running" | "waiting_approval" | "completed" | "failed";
  turnIndex: number;
}

const emptySession = (): SessionState => ({
  items: [],
  toolCalls: {},
  artifacts: {},
  artifactOrder: [],
  loadedSkills: [],
  disclaimer: null,
  plan: [],
  pending: null,
  usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, cost_usd: 0 },
  status: "idle",
  turnIndex: 0,
});

/** UI state for the artifact/tool side panel. */
export type PanelMode =
  | { kind: "closed" }
  | { kind: "artifact"; artifactId: string }
  | { kind: "tool"; toolCallId: string };

interface State {
  user: User | null;
  setUser: (u: User | null) => void;

  sessions: Record<string, SessionState>;
  activeSessionId: string | null;
  setActiveSessionId: (id: string | null) => void;

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
  closePanel: () => void;
  setArtifactView: (v: "preview" | "source") => void;
  setToolView: (v: "result" | "arguments") => void;
}

const toolCallId = (step: number, name: string) => `${step}:${name}`;

export const useStore = create<State>()((set, get) => ({
  user: null,
  setUser: (u) => set({ user: u }),

  sessions: {},
  activeSessionId: null,
  setActiveSessionId: (id) => set({ activeSessionId: id }),

  resetSession: (sid) =>
    set((s) => ({ sessions: { ...s.sessions, [sid]: emptySession() } })),

  ingest: (sid, ev) => {
    const sessions = { ...get().sessions };
    const st = { ...(sessions[sid] ?? emptySession()) };
    st.items = [...st.items];
    st.toolCalls = { ...st.toolCalls };
    st.artifacts = { ...st.artifacts };

    const ti = st.turnIndex;

    switch (ev.type) {
      case "turn_started":
        st.turnIndex += 1;
        st.items.push({ kind: "user", text: ev.user_input, turnIndex: st.turnIndex });
        st.items.push({ kind: "assistant", content: "", streaming: true, turnIndex: st.turnIndex });
        st.status = "running";
        st.pending = null;
        break;

      case "assistant_token": {
        // Append to the most recent streaming assistant item.
        for (let i = st.items.length - 1; i >= 0; i--) {
          const it = st.items[i];
          if (it.kind === "assistant" && it.streaming) {
            st.items[i] = { ...it, content: it.content + ev.text };
            break;
          }
        }
        break;
      }

      case "assistant_note": {
        // The runtime emits assistant_note containing the SAME full text it
        // just streamed via assistant_token events (before calling a tool).
        // Dedupe: if the most recent assistant item already has this content,
        // just finalize it instead of pushing a duplicate.
        let deduped = false;
        for (let i = st.items.length - 1; i >= 0; i--) {
          const it = st.items[i];
          if (it.kind !== "assistant") continue;
          if (it.content.trim() === ev.text.trim()) {
            st.items[i] = { ...it, streaming: false };
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
        break;

      case "turn_finished": {
        let updated = false;
        for (let i = st.items.length - 1; i >= 0; i--) {
          const it = st.items[i];
          if (it.kind === "assistant" && it.streaming) {
            st.items[i] = { ...it, content: ev.content || it.content, streaming: false };
            updated = true;
            break;
          }
        }
        if (!updated && ev.content?.trim()) {
          const last = st.items[st.items.length - 1];
          const sameAsLastAssistant =
            last?.kind === "assistant" && last.content.trim() === ev.content.trim();
          if (!sameAsLastAssistant) {
            st.items.push({
              kind: "assistant",
              content: ev.content,
              streaming: false,
              turnIndex: ti,
            });
          }
        }
        break;
      }

      case "tool_started": {
        const id = toolCallId(ev.step, ev.name);
        st.toolCalls[id] = {
          id,
          step: ev.step,
          name: ev.name,
          arguments: ev.arguments,
          status: "running",
        };
        st.items.push({ kind: "tool", toolCallId: id, turnIndex: ti });
        break;
      }

      case "tool_finished": {
        const id = toolCallId(ev.step, ev.name);
        const existing = st.toolCalls[id];
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
        // No step in the denied event; attach to the most recent running
        // call with the same name as a best-effort match.
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

      case "plan_updated":
        st.plan = ev.steps;
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
        st.items.push({ kind: "artifact", artifactId: ev.artifact_id, turnIndex: ti });
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

    sessions[sid] = st;
    set({ sessions });
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
  closePanel: () => set((s) => ({ ui: { ...s.ui, panel: { kind: "closed" } } })),
  setArtifactView: (v) => set((s) => ({ ui: { ...s.ui, artifactView: v } })),
  setToolView: (v) => set((s) => ({ ui: { ...s.ui, toolView: v } })),
}));
