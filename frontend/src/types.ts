/** Event schema mirrors `core/src/agent/events/schema.py`. */

export type ArtifactKind =
  | "code" | "markdown" | "text" | "json"
  | "wealth_snapshot" | "path_comparison" | "action_checklist"
  | "image" | "pdf" | "file" | "terminal_log" | "plan" | "app_preview";

export interface AgentEventBase {
  session_id: string;
  turn_id: string | null;
  seq: number;
  timestamp: number;
}

export interface SearchResultCard {
  title: string;
  url: string;
  snippet: string;
  source?: string | null;
  timestamp?: string | null;
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
  | (AgentEventBase & { type: "education_disclaimer"; message: string; scope: "education" })
  | (AgentEventBase & { type: "skill_auto_loaded"; skill_name: string })
  | (AgentEventBase & { type: "plan_updated"; steps: PlanStep[] })
  | (AgentEventBase & { type: "tool_started"; step: number; name: string; arguments: Record<string, unknown> })
  | (AgentEventBase & { type: "tool_finished"; step: number; name: string; arguments: Record<string, unknown>; success: boolean; duration_ms: number; content: string; search_results?: SearchResultCard[] })
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

export type TodoStatus = "pending" | "in_progress" | "completed" | "failed";

export interface TodoItem {
  id: string;
  text: string;
  status: TodoStatus;
}

export type PlanStep = TodoItem;

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
  mime?: string | null;
  description?: string | null;
  content: string;
  finalized: boolean;
  size?: number | null;
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

export interface FinancialProfile {
  income: number;
  cash: number;
  monthly_expenses: number;
  retirement: number;
  brokerage: number;
  rsus: number;
  home_equity: number;
  student_loans: number;
  student_loan_rate: number;
  credit_card_debt: number;
  other_debt: number;
  goals: string[];
  home_purchase_horizon: string | null;
}

export interface WealthSnapshot {
  schema_version: number;
  income: number;
  monthly_expenses: number;
  net_worth: number;
  liquid_net_worth: number;
  allocation: {
    cash: number;
    retirement: number;
    brokerage: number;
    rsus: number;
    home_equity: number;
    debt_total: number;
  };
  emergency_fund: {
    months_covered: number;
    target_months: number;
  };
  goals: string[];
  debt_breakdown: Array<{ name: string; amount: number; rate: number }>;
  situation: string;
  flags: string[];
  ratios: {
    cash_ratio: number;
    rsu_ratio: number;
    debt_ratio: number;
  };
}

export interface PathCard {
  name: string;
  headline: string;
  pros: string[];
  cons: string[];
  best_for: string;
  required_concepts: string[];
}

export interface PathComparison {
  schema_version: number;
  snapshot_id: string;
  situation: string;
  paths: PathCard[];
}

export interface ChecklistItemState {
  artifact_id: string;
  item_index: number;
  text: string;
  completed: boolean;
  completed_at?: number | null;
}
