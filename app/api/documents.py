from fastapi import APIRouter, File, UploadFile

from app.api.deps import DocumentsDep, RagDep
from app.schemas.documents import (
    DeleteResponse,
    DocumentListResponse,
    IndexStatus,
    RebuildRequest,
    RebuildResponse,
    UploadResponse,
)

router = APIRouter(prefix="/api/v1", tags=["Documents"])


@router.get("/documents", response_model=DocumentListResponse)
def list_documents(documents: DocumentsDep, rag: RagDep):
    """
    Every document in the knowledge-base folder with its index status, plus
    a summary of the index itself.
    """

    return {
        "documents": documents.list_documents(),
        "index": rag.index_status(),
    }


@router.post("/documents", response_model=UploadResponse, status_code=201)
async def upload_document(documents: DocumentsDep, file: UploadFile = File(...)):
    """
    Save one document. It becomes searchable after the next index rebuild.
    """

    contents = await file.read()

    saved = documents.save_upload(file.filename, contents)

    return {
        **saved,
        "message": (
            f"{'Replaced' if saved['replaced'] else 'Uploaded'} {saved['name']}. "
            "Rebuild the index to make it searchable."
        ),
    }


@router.delete("/documents/{name}", response_model=DeleteResponse)
def delete_document(name: str, documents: DocumentsDep):
    """
    Remove a document file. Its chunks stay searchable until the next rebuild.
    """

    deleted = documents.delete(name)

    return {
        **deleted,
        "message": f"Deleted {deleted['name']}. Rebuild the index to remove its chunks.",
    }


@router.get("/index", response_model=IndexStatus)
def index_status(rag: RagDep):
    return rag.index_status()


@router.post("/index/rebuild", response_model=RebuildResponse)
def rebuild_index(rag: RagDep, request: RebuildRequest | None = None):
    """
    Rebuild the whole index from the documents folder with the chosen
    chunking strategy. Replaces the previous index entirely.
    """

    strategy = request.strategy if request else "heading"

    return rag.ingest(strategy=strategy)


# Kept for callers of the original POC endpoint.
@router.post("/ingest", response_model=RebuildResponse, include_in_schema=False)
def ingest_alias(rag: RagDep, request: RebuildRequest | None = None):
    return rebuild_index(rag, request)
