from fastapi import APIRouter, HTTPException

from app.schemas.ingestSchemas import IngestRequest, IngestResponse
from app.services.shared import rag_service

router = APIRouter(
    prefix="/api/v1",
    tags=["Ingest"]
)


@router.post("/ingest", response_model=IngestResponse)
async def ingest(request: IngestRequest | None = None):
    """
    Rebuild the index from the documents in the data folder, using
    the requested chunking strategy (defaults to heading-based).
    """

    strategy = request.strategy if request else "heading"

    try:
        return rag_service.ingest(strategy=strategy)
    except FileNotFoundError as error:
        raise HTTPException(status_code=400, detail=str(error))
