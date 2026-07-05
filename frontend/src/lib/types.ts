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

export interface RunEvent {
  type: "step" | "run_finished" | "run_cancelled";
  run_id?: string;
  agent?: string;
  kind?: "llm_call" | "tool_call";
  tool?: string;
  summary?: string;
  step?: number;
  cost_usd?: number;
  error?: boolean | string | null;
  status?: RunStatus;
}
