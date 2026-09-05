from typing import Literal

from pydantic import BaseModel

from app.schemas.common import ChunkStrategy

DocumentStatus = Literal["indexed", "pending", "removed"]


class DocumentInfo(BaseModel):
    name: str
    extension: str
    bytes: int | None
    modified_at: str | None
    status: DocumentStatus
    pages: int | None
    words: int | None
    chunks: int | None


class IndexStatus(BaseModel):
    chunks: int
    ready: bool
    strategy: str | None
    built_at: str | None
    documents: int | None
    words: int | None
    collection: str
    embedding_model: str


class DocumentListResponse(BaseModel):
    documents: list[DocumentInfo]
    index: IndexStatus


class UploadResponse(BaseModel):
    name: str
    bytes: int
    replaced: bool
    message: str


class DeleteResponse(BaseModel):
    name: str
    message: str


class RebuildRequest(BaseModel):
    strategy: ChunkStrategy = "heading"


class DocumentStat(BaseModel):
    source: str
    pages: int
    words: int
    chunks: int


class RebuildResponse(BaseModel):
    strategy: str
    documents: int
    words: int
    chunks: int
    built_at: str
    per_document: list[DocumentStat]
