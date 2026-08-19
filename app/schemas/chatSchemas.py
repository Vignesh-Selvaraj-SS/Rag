from pydantic import BaseModel


class ChatRequest(BaseModel):
    question: str


class Source(BaseModel):
    source: str
    heading: str
    page: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
