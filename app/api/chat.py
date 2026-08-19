from fastapi import APIRouter, HTTPException

from app.schemas.chatSchemas import ChatRequest, ChatResponse
from app.services.shared import rag_service

router = APIRouter(
    prefix="/api/v1/chat",
    tags=["Chat"]
)


def require_index():

    if rag_service.chunk_count() == 0:
        raise HTTPException(
            status_code=503,
            detail="The index is empty. POST /api/v1/ingest first."
        )


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest):

    require_index()

    result = rag_service.ask(request.question)

    return {
        "answer": result["answer"],
        "sources": [
            {
                "source": hit["source"],
                "heading": hit["heading"],
                "page": hit["page"],
            }
            for hit in result["sources"]
        ],
    }
