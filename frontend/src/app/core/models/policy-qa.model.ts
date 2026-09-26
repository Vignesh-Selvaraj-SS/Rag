export interface PolicyQaStep {
  step: number;
  tool: string;
  thought: string | null;
  args: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  latency_ms: number;
  tokens: number | null;
}

export interface PolicyQaSystemResult {
  answer: string | null;
  sources: string[];
  steps: PolicyQaStep[];
  step_count: number;
  tokens_used: number;
  latency_ms: number;
  stopped_reason: string;
  finished: boolean;
  error: string | null;
}

export type PolicyQaSystemChoice = 'both' | 'agent' | 'workflow';

export interface PolicyQaRequest {
  question: string;
  system: PolicyQaSystemChoice;
}

export interface PolicyQaResponse {
  question: string;
  agent: PolicyQaSystemResult | null;
  workflow: PolicyQaSystemResult | null;
}
