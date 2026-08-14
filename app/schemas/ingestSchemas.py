from pydantic import BaseModel


class DocumentStat(BaseModel):
    source: str
    pages: int
    words: int
    chunks: int


class IngestResponse(BaseModel):
    documents: int
    words: int
    chunks: int
    per_document: list[DocumentStat]
