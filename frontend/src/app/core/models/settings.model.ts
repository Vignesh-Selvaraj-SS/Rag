import { RetrievalMode } from './chat.model';
import { ChunkStrategy } from './documents.model';

export interface RetrievalModeInfo {
  id: RetrievalMode;
  label: string;
  description: string;
  requires_llm: boolean;
}

export interface ChunkStrategyInfo {
  id: ChunkStrategy;
  label: string;
  description: string;
}

export interface AppSettings {
  app_name: string;
  version: string;
  embedding_model: string;
  collection: string;
  defaults: { mode: RetrievalMode; top_k: number; min_score: number };
  generation: {
    model: string;
    temperature: number;
    max_tokens: number;
    prompt_version: string;
    configured: boolean;
  };
  constants: {
    candidate_pool_size: number;
    rrf_k: number;
    mmr_lambda: number;
    reranker_model: string;
    fixed_chunk_words: number;
    fixed_chunk_overlap_words: number;
    hnsw_m: number;
    hnsw_ef_construct: number;
    hnsw_ef_search: number;
  };
  modes: RetrievalModeInfo[];
  strategies: ChunkStrategyInfo[];
  traces_enabled: boolean;
  max_upload_mb: number;
  supported_extensions: string[];
}

export interface HealthResponse {
  status: string;
  version: string;
  index_chunks: number;
  index_ready: boolean;
  llm_configured: boolean;
}

/** Client-side preferences, persisted in localStorage. */
export interface UserPreferences {
  mode: RetrievalMode;
  topK: number | null;
  minScore: number | null;
  source: string | null;
  developerMode: boolean;
  theme: 'system' | 'light' | 'dark';
}
