"""
A small JSON record written next to the Qdrant data every time the index is
rebuilt. Qdrant stores the vectors; this stores what the vectors were built
from - strategy, time, per-document counts - so the UI can say "122 chunks,
heading strategy, built 5 minutes ago" without re-reading the corpus.
"""

import json
from datetime import datetime, timezone
from pathlib import Path


class IndexMetadata:

    def __init__(self, path: Path):
        self.path = path

    def read(self) -> dict | None:

        if not self.path.exists():
            return None

        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def write(self, ingest_result: dict) -> dict:

        record = {
            "strategy": ingest_result["strategy"],
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "documents": ingest_result["documents"],
            "words": ingest_result["words"],
            "chunks": ingest_result["chunks"],
            "per_document": ingest_result["per_document"],
        }

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(record, indent=2), encoding="utf-8")

        return record

    def clear(self) -> None:

        if self.path.exists():
            self.path.unlink()
