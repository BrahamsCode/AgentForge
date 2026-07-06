export type Provider = "anthropic" | "openai" | "ollama";

export type RunStatus =
  | "queued"
  | "running"
  | "awaiting_approval"
  | "completed"
  | "failed"
  | "cancelled";

export interface Agent {
  id: string;
  name: string;
  role: string;
  model_provider: Provider;
  model_name: string;
  system_prompt: string;
  max_steps: number;
  max_cost_usd: number;
  temperature: number | null;
  created_at: string;
}

export interface AskResponse {
  answer: string;
  model_provider: Provider;
  model_name: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  latency_ms: number;
}

export interface TeamMember {
  agent_id: string;
  agent_name: string;
  specialty: string;
}

export interface Team {
  id: string;
  name: string;
  description: string;
  orchestrator_agent_id: string | null;
  created_at: string;
  members: TeamMember[];
}

export interface Run {
  id: string;
  agent_id: string | null;
  team_id: string | null;
  goal: string;
  status: RunStatus;
  error: string | null;
  total_cost_usd: number;
  total_tokens: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  final_answer: string | null;
}

export interface TraceStep {
  id: string;
  step_number: number;
  kind: "llm_call" | "tool_call" | "approval" | "checkpoint" | "error";
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  latency_ms: number;
  created_at: string;
}

export interface Approval {
  id: string;
  run_id: string;
  action_summary: string;
  status: "pending" | "approved" | "rejected";
  created_at: string;
  decided_at: string | null;
}

export type OrgRole = "owner" | "admin" | "member";

export interface OrgMember {
  org_id: string;
  user_id: string;
  role: OrgRole;
}

export interface Organization {
  id: string;
  name: string;
  plan: string;
  max_runs_per_day: number;
  max_cost_usd_per_day: number;
  created_at: string;
  members?: OrgMember[];
}

export interface AgentMessage {
  id: string;
  from_agent_name: string;
  to_agent: string;
  content: string;
  read: boolean;
  created_at: string;
}

export interface RunEvent {
  type:
    | "step"
    | "run_finished"
    | "run_cancelled"
    | "approval_required"
    | "approval_decided";
  run_id?: string;
  agent?: string;
  kind?: "llm_call" | "tool_call";
  tool?: string;
  summary?: string;
  step?: number;
  cost_usd?: number;
  error?: boolean | string | null;
  status?: RunStatus;
  approval_id?: string;
  decision?: string;
}

export interface TemplateMemberSpec {
  name: string;
  role: string;
  model_provider: Provider;
  model_name: string;
  system_prompt?: string;
  specialty?: string;
}

export interface TemplateSpec {
  orchestrator: TemplateMemberSpec;
  members: TemplateMemberSpec[];
}

export interface TeamTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  spec: TemplateSpec;
  is_builtin: boolean;
  created_at: string;
}
