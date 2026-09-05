"""
The documents on disk, joined with what the index knows about them.

A file's status is derived, never stored:

    indexed   in the last build, unchanged since
    pending   uploaded or modified after the last build (needs a rebuild)
    removed   still in the index but the file is gone (rebuild to drop it)
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

from app.core.errors import BadRequestError, NotFoundError
from app.services.document_loader import SUPPORTED_EXTENSIONS
from app.services.index_metadata import IndexMetadata

logger = logging.getLogger(__name__)


def safe_filename(name: str | None) -> str:
    """
    Reduce a client-supplied filename to its final path component so a
    crafted name like "../../app/main.py" can only ever land inside the
    data folder.
    """

    cleaned = Path(name or "").name.strip()

    if not cleaned or cleaned in {".", ".."}:
        raise BadRequestError("A file name is required.")

    if cleaned.startswith("."):
        raise BadRequestError("Hidden files are not accepted.")

    return cleaned


def validate_extension(name: str) -> str:

    suffix = Path(name).suffix.lower()

    if suffix not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise BadRequestError(
            f"Unsupported file type '{suffix or 'none'}'. Allowed: {allowed}."
        )

    return suffix


class DocumentService:

    def __init__(self, data_dir: Path, index_metadata: IndexMetadata, max_upload_bytes: int):

        self.data_dir = data_dir
        self.index_metadata = index_metadata
        self.max_upload_bytes = max_upload_bytes

    # ------------------------------------------------------------------ read

    def list_documents(self) -> list[dict]:

        metadata = self.index_metadata.read()
        built_at = _parse_time(metadata["built_at"]) if metadata else None
        indexed = {row["source"]: row for row in (metadata or {}).get("per_document", [])}

        documents = []
        seen = set()

        if self.data_dir.exists():

            for path in sorted(self.data_dir.iterdir()):

                if not path.is_file() or path.name.startswith("."):
                    continue

                if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    continue

                stat = path.stat()
                # Second precision, matching how built_at is recorded, so a
                # file saved in the same second as the build counts as indexed.
                modified = datetime.fromtimestamp(int(stat.st_mtime), tz=timezone.utc)
                row = indexed.get(path.name)

                if row is None or built_at is None or modified > built_at:
                    status = "pending"
                else:
                    status = "indexed"

                seen.add(path.name)

                documents.append(
                    {
                        "name": path.name,
                        "extension": path.suffix.lower().lstrip("."),
                        "bytes": stat.st_size,
                        "modified_at": modified.isoformat(timespec="seconds"),
                        "status": status,
                        "pages": row["pages"] if row else None,
                        "words": row["words"] if row else None,
                        "chunks": row["chunks"] if row else None,
                    }
                )

        for source, row in indexed.items():

            if source in seen:
                continue

            documents.append(
                {
                    "name": source,
                    "extension": Path(source).suffix.lower().lstrip("."),
                    "bytes": None,
                    "modified_at": None,
                    "status": "removed",
                    "pages": row["pages"],
                    "words": row["words"],
                    "chunks": row["chunks"],
                }
            )

        return documents

    # ----------------------------------------------------------------- write

    def save_upload(self, filename: str | None, contents: bytes) -> dict:

        name = safe_filename(filename)
        validate_extension(name)

        if not contents:
            raise BadRequestError("The uploaded file is empty.")

        if len(contents) > self.max_upload_bytes:
            limit_mb = self.max_upload_bytes // (1024 * 1024)
            raise BadRequestError(
                f"The file is too large ({len(contents):,} bytes). "
                f"The limit is {limit_mb} MB."
            )

        self.data_dir.mkdir(parents=True, exist_ok=True)

        target = self.data_dir / name
        replaced = target.exists()
        target.write_bytes(contents)

        logger.info("Saved document %s (%d bytes, replaced=%s)", name, len(contents), replaced)

        return {"name": name, "bytes": len(contents), "replaced": replaced}

    def delete(self, filename: str) -> dict:

        name = safe_filename(filename)
        target = self.data_dir / name

        if not target.is_file():
            raise NotFoundError(f"No document named '{name}' exists.")

        target.unlink()

        logger.info("Deleted document %s", name)

        return {"name": name}


def _parse_time(value: str) -> datetime | None:

    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed
