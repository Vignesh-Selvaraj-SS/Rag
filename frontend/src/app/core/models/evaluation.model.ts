import { RetrievalMode } from './chat.model';

export interface GoldenQuestion {
  id: string;
  question: string;
  expected_chunk_id: string;
  expected_heading: string | null;
  exact_token: string | null;
}

export interface EvaluationRunRequest {
  mode: RetrievalMode;
  top_k: number;
  label: string | null;
}

export interface EvaluationHit {
  rank: number;
  chunk_id: string;
  source: string;
  heading: string;
  score: number;
  dense_score: number;
  expected: boolean;
}

export interface EvaluationQuestionResult {
  id: string;
  question: string;
  expected_chunk_id: string;
  expected_heading: string | null;
  exact_token: string | null;
  rank_of_expected: number | null;
  hit_at_3: boolean;
  hit_at_5: boolean;
  latency_ms: number;
  top_hits: EvaluationHit[];
}

export interface EvaluationRunSummary {
  run_id: string;
  created_at: string;
  label: string | null;
  mode: RetrievalMode;
  top_k: number;
  index: { strategy: string | null; chunks: number | null; built_at: string | null };
  n_questions: number;
  hit_rate_at_3: number;
  hit_rate_at_5: number;
  hits_at_3: number;
  hits_at_5: number;
  mrr: number;
  p50_latency_ms: number;
  warnings: string[];
}

export interface EvaluationRun extends EvaluationRunSummary {
  per_question: EvaluationQuestionResult[];
}

export interface InspectChunk {
  rank: number;
  chunk_id: string;
  source: string;
  heading: string;
  page: string;
  score: number;
  dense_score: number;
  text: string;
  expected: boolean;
}

export interface InspectResponse {
  question_id: string;
  question: string;
  expected_chunk_id: string;
  expected_heading: string | null;
  mode: RetrievalMode;
  expected_was_shown: boolean;
  retrieved: InspectChunk[];
  answer: string;
  refused: boolean;
  refused_by: 'gate' | 'model' | null;
  cited_chunk_ids: string[];
  invalid_citations: string[];
  latency_ms: number;
}
