export type RetrievalMode = 'dense' | 'hybrid' | 'rerank' | 'mmr' | 'rewrite' | 'hyde';

export interface RetrievalOptions {
  mode: RetrievalMode;
  top_k: number | null;
  min_score: number | null;
  source: string | null;
}

export interface ChatRequest extends RetrievalOptions {
  question: string;
  include_debug: boolean;
}

export interface RetrievedChunk {
  rank: number;
  chunk_id: string;
  source: string;
  heading: string;
  page: string;
  score: number;
  dense_score: number;
  text: string;
}

export interface Source {
  rank: number;
  chunk_id: string;
  source: string;
  heading: string;
  page: string;
}

export interface ChatDebug {
  retrieved: RetrievedChunk[];
  params: Record<string, unknown>;
  model: string;
  prompt_version: string;
  passes_gate: boolean;
  best_score: number;
  invalid_citations: string[];
  raw_output: string | null;
}

export type RefusedBy = 'gate' | 'model' | null;

export interface ChatResponse {
  answer: string;
  sources: Source[];
  refused: boolean;
  refused_by: RefusedBy;
  mode: RetrievalMode;
  latency_ms: number;
  trace_id: string | null;
  debug: ChatDebug | null;
}

export interface SearchRequest extends RetrievalOptions {
  question: string;
}

export interface SearchResponse {
  question: string;
  hits: RetrievedChunk[];
  best_score: number;
  passes_gate: boolean;
  min_score: number;
  mode: RetrievalMode;
  latency_ms: number;
}
