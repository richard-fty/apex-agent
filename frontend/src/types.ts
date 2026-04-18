/** Event schema mirrors `core/src/agent/events/schema.py`. */

export type ArtifactKind =
  | "code" | "markdown" | "text" | "json"
  | "image" | "pdf" | "file" | "terminal_log" | "plan";

export interface AgentEventBase {
  session_id: string;
  turn_id: string | null;
  seq: number;
  timestamp: number;
}

export type AgentEvent =
  | (AgentEventBase & { type: "session_created"; model: string; owner_user_id: string | null })
  | (AgentEventBase & { type: "turn_started"; user_input: string })
  | (AgentEventBase & { type: "turn_finished"; content: string })
  | (AgentEventBase & { type: "stream_end"; final_state: "completed" | "waiting_approval" | "failed" | "cancelled"; reason: string | null })
  | (AgentEventBase & { type: "error"; message: string })
  | (AgentEventBase & { type: "assistant_token"; text: string })
  | (AgentEventBase & { type: "assistant_message"; content: string })
  | (AgentEventBase & { type: "assistant_note"; text: string })
  | (AgentEventBase & { type: "skill_auto_loaded"; skill_name: string })
  | (AgentEventBase & { type: "plan_updated"; steps: PlanStep[] })
  | (AgentEventBase & { type: "tool_started"; step: number; name: string; arguments: Record<string, unknown> })
  | (AgentEventBase & { type: "tool_finished"; step: number; name: string; arguments: Record<string, unknown>; success: boolean; duration_ms: number; content: string })
  | (AgentEventBase & { type: "tool_denied"; name: string; reason: string })
  | (AgentEventBase & { type: "approval_requested"; step: number; tool_name: string; reason: string })
  | (AgentEventBase & { type: "approval_resolved"; tool_name: string; action: string })
  | (AgentEventBase & { type: "artifact_created"; artifact_id: string; kind: ArtifactKind; name: string; language: string | null; mime: string | null; description: string | null })
  | (AgentEventBase & { type: "artifact_patch"; artifact_id: string; op: "append" | "replace"; text: string | null; content: string | null })
  | (AgentEventBase & { type: "artifact_finalized"; artifact_id: string; size: number; checksum: string | null })
  | (AgentEventBase & { type: "artifact_deleted"; artifact_id: string })
  | (AgentEventBase & { type: "sandbox_exec_started"; exec_id: string; cmd: string; cwd: string | null })
  | (AgentEventBase & { type: "sandbox_exec_output"; exec_id: string; stream: "stdout" | "stderr"; text: string })
  | (AgentEventBase & { type: "sandbox_exec_finished"; exec_id: string; exit_code: number; duration_ms: number })
  | (AgentEventBase & { type: "usage"; step: number; usage: TokenUsage; duration_ms: number });

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
}

export interface PlanStep {
  id: string;
  text: string;
  status: "pending" | "in_progress" | "completed" | "cancelled";
}

export interface Session {
  id: string;
  model: string;
  context_strategy: string;
  state: string;
  created_at: number;
}

export interface User {
  id: string;
  username: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
}

export interface Artifact {
  id: string;
  kind: ArtifactKind;
  name: string;
  language?: string | null;
  description?: string | null;
  content: string;
  finalized: boolean;
}

export interface ApprovalRequest {
  tool_name: string;
  reason: string;
  step: number;
}

export interface Skill {
  name: string;
  description: string;
  keywords: string[];
  loaded: boolean;
}
