export interface AgentClaimSummary {
  claim_id: string;
  claimed_amount: number;
  policy_form: string;
}

export interface AgentStep {
  step: number;
  tool: string;
  thought: string | null;
  args: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  latency_ms: number;
  tokens: number | null;
}

export type AgentSystemChoice = 'both' | 'agent' | 'workflow';

export interface AgentSystemResult {
  answer: string | null;
  decision: string | null;
  payout: number | null;
  sources: string[];
  steps: AgentStep[];
  step_count: number;
  tokens_used: number;
  cost_usd: number;
  latency_ms: number;
  stopped_reason: string;
  finished: boolean;
  error: string | null;
}

export interface AgentRunRequest {
  user_input: string;
  system: AgentSystemChoice;
}

export interface AgentRunResponse {
  user_input: string;
  agent: AgentSystemResult | null;
  workflow: AgentSystemResult | null;
}
