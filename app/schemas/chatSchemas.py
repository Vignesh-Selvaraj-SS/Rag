from typing import Literal

from pydantic import BaseModel


class ChatRequest(BaseModel):
    question: str
    mode: Literal["dense", "hybrid", "rerank", "mmr", "rewrite", "hyde"] = "dense"


class Source(BaseModel):
    source: str
    heading: str
    page: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
