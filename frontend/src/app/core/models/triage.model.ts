export interface TriageClaimSummary {
  claim_id: string;
  claimed_amount: number;
  policy_form: string;
}

export interface TriageStep {
  step: number;
  tool: string;
  thought: string | null;
  args: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  latency_ms: number;
  tokens: number | null;
}

export interface TriageSystemResult {
  decision: string | null;
  payout: number | null;
  reasoning: string;
  sources: string[];
  steps: TriageStep[];
  step_count: number;
  tokens_used: number;
  cost_usd: number;
  latency_ms: number;
  stopped_reason: string;
  finished: boolean;
  error: string | null;
}

export interface TriageRunRequest {
  claim_id: string;
}

export interface TriageRunResponse {
  claim_id: string;
  agent: TriageSystemResult;
  workflow: TriageSystemResult;
}
