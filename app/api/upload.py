from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.config import DATA_DIR
from app.schemas.uploadSchemas import UploadResponse
from app.services.document_loader import SUPPORTED_EXTENSIONS

router = APIRouter(
    prefix="/api/v1",
    tags=["Upload"]
)

# Generous for a policy PDF, small enough to not accept an accidental
# multi-hundred-MB upload.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@router.post("/documents", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)):
    """
    Save one document into data/. Does not ingest it - POST
    /api/v1/ingest afterwards to add it to the searchable index.
    """

    # Path(...).name strips any directory components from the
    # supplied filename, so a crafted name like "../../app/main.py"
    # can only ever write inside DATA_DIR, never escape it.
    safe_name = Path(file.filename or "").name
    suffix = Path(safe_name).suffix.lower()

    if not safe_name or suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{suffix}'. "
                f"Allowed: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            ),
        )

    contents = await file.read()

    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({len(contents):,} bytes). Max {MAX_UPLOAD_BYTES:,} bytes.",
        )

    (DATA_DIR / safe_name).write_bytes(contents)

    return {
        "filename": safe_name,
        "bytes": len(contents),
        "message": "Uploaded. Click Rebuild index to add it to the searchable index.",
    }
