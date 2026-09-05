export type ChunkStrategy = 'heading' | 'fixed_size';

export type DocumentStatus = 'indexed' | 'pending' | 'removed';

export interface DocumentInfo {
  name: string;
  extension: string;
  bytes: number | null;
  modified_at: string | null;
  status: DocumentStatus;
  pages: number | null;
  words: number | null;
  chunks: number | null;
}

export interface IndexStatus {
  chunks: number;
  ready: boolean;
  strategy: ChunkStrategy | null;
  built_at: string | null;
  documents: number | null;
  words: number | null;
  collection: string;
  embedding_model: string;
}

export interface DocumentListResponse {
  documents: DocumentInfo[];
  index: IndexStatus;
}

export interface UploadResponse {
  name: string;
  bytes: number;
  replaced: boolean;
  message: string;
}

export interface DeleteResponse {
  name: string;
  message: string;
}

export interface DocumentStat {
  source: string;
  pages: number;
  words: number;
  chunks: number;
}

export interface RebuildResponse {
  strategy: ChunkStrategy;
  documents: number;
  words: number;
  chunks: number;
  built_at: string;
  per_document: DocumentStat[];
}
