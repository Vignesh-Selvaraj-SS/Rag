from typing import Literal

from pydantic import BaseModel


class IngestRequest(BaseModel):
    strategy: Literal["heading", "fixed_size"] = "heading"


class DocumentStat(BaseModel):
    source: str
    pages: int
    words: int
    chunks: int


class IngestResponse(BaseModel):
    strategy: str
    documents: int
    words: int
    chunks: int
    per_document: list[DocumentStat]
