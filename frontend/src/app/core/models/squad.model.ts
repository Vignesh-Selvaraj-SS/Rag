export interface SquadHandoff {
  from: string;
  to: string;
  tokens: number;
  error?: string;
}

export interface SquadRunRequest {
  notes: string;
  simulate_coverage_worker_failure: boolean;
}

export interface SquadRunResponse {
  notes: string;
  summary: string | null;
  fields: Record<string, string | null>;
  sources: string[];
  handoffs: SquadHandoff[];
  intermediate: Record<string, string>;
  worker_error: string | null;
  tokens_used: number;
  cost_usd: number;
  latency_ms: number;
  error: string | null;
}

export interface SquadRaceStartRequest {
  only?: string[] | null;
  sleep?: number;
}

export interface SquadRaceCaseStatus {
  id: string;
  single_status: string | null;
  squad_status: string | null;
  fail_injected: boolean;
}

export interface SquadRaceArmSummary {
  n: number;
  pass_rate: number;
  p50_latency_ms: number;
  p99_latency_ms: number;
  total_tokens: number;
  cost_per_claim_usd: number;
}

export interface SquadRaceStatusResponse {
  running: boolean;
  current: string | null;
  error: string | null;
  total_cases: number;
  completed_pairs: number;
  total_pairs: number;
  per_case: SquadRaceCaseStatus[];
  single_summary: SquadRaceArmSummary | null;
  squad_summary: SquadRaceArmSummary | null;
  context_resend_multiplier: number | null;
  handoff_totals: Record<string, number>;
}
