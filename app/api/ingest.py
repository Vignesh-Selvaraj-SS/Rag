from fastapi import APIRouter, HTTPException

from app.schemas.ingestSchemas import IngestResponse
from app.services.shared import rag_service

router = APIRouter(
    prefix="/api/v1",
    tags=["Ingest"]
)


@router.post("/ingest", response_model=IngestResponse)
async def ingest():
    """
    Rebuild the index from the documents in the data folder.
    """

    try:
        return rag_service.ingest()
    except FileNotFoundError as error:
        raise HTTPException(status_code=400, detail=str(error))
