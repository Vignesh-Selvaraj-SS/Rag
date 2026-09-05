export type CheckStatus = 'pass' | 'fail' | 'review' | 'skip';
export type OverallCheckStatus = 'pass' | 'fail' | 'review';

export interface TraceCheck {
  id: string;
  name: string;
  status: CheckStatus;
  detail: string;
}

export interface TraceSummary {
  trace_id: string;
  timestamp: string | null;
  origin: string | null;
  question: string | null;
  mode: string | null;
  model: string | null;
  refused: boolean;
  refused_by: 'gate' | 'model' | null;
  latency_ms: number;
  retrieved_count: number;
  cited_count: number;
  invalid_citations: number;
  check_status: OverallCheckStatus;
}

export interface TraceListResponse {
  total: number;
  items: TraceSummary[];
}

export interface TraceChunk {
  rank: number;
  chunk_id: string;
  source: string;
  heading: string;
  page: string;
  score: number;
  dense_score: number;
  text: string | null;
}

export interface TraceDetail {
  trace_id: string;
  timestamp: string | null;
  origin: string | null;
  question: string | null;
  identifiers_redacted: number;
  model: string | null;
  prompt_version: string | null;
  params: Record<string, unknown>;
  chunk_strategy: string | null;
  retrieved: TraceChunk[];
  passes_gate: boolean;
  raw_output: string | null;
  answer: string | null;
  cited_chunk_ids: string[];
  invalid_citations: string[];
  refused: boolean;
  refused_by: 'gate' | 'model' | null;
  latency_ms: number;
  checks: TraceCheck[];
  check_status: OverallCheckStatus;
}

export interface TraceSampleResponse {
  seed: number;
  frame: number;
  selected: number;
  items: TraceSummary[];
}

export interface TraceStats {
  total: number;
  answered: number;
  refused: number;
  refused_by_gate: number;
  refused_by_model: number;
  answered_without_citation: number;
  with_invalid_citations: number;
  identifiers_redacted: number;
  latency_p50_ms: number;
  latency_p95_ms: number;
  latency_avg_ms: number;
  by_mode: Record<string, number>;
  by_model: Record<string, number>;
  checks: Record<'pass' | 'review' | 'fail', number>;
  top_sources: { source: string; citations: number }[];
  by_day: { day: string; count: number }[];
}

export interface ReplayChunk {
  chunk_id: string;
  score: number;
}

export interface ReplayResponse {
  trace_id: string;
  retrieval: {
    original: ReplayChunk[];
    replayed: ReplayChunk[];
    identical: boolean;
    same_chunks: boolean;
  };
  generation: {
    skipped: boolean;
    reason: string | null;
    original: string | null;
    replayed: string | null;
    identical: boolean | null;
    diff: string[];
    prompt_version_then: string | null;
    prompt_version_now: string | null;
  } | null;
}

export interface TraceListQuery {
  limit?: number;
  offset?: number;
  refused?: boolean | null;
  mode?: string | null;
  search?: string | null;
}
