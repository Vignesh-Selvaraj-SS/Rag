"""
Build the search index from the documents in data/.

    python scripts/ingest.py
    python scripts/ingest.py --strategy fixed_size

Stop the API server first: embedded Qdrant locks its folder to one process.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.services.catalog import STRATEGY_IDS  # noqa: E402
from app.services.shared import get_rag_service  # noqa: E402


def main() -> int:

    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=STRATEGY_IDS, default="heading")
    args = parser.parse_args()

    print(f"Embedding with {settings.EMBEDDING_MODEL} (strategy: {args.strategy}) ...")

    result = get_rag_service().ingest(strategy=args.strategy)

    print(f"\n{'document':<48}{'pages':>7}{'words':>8}{'chunks':>8}")
    print("-" * 71)

    for row in result["per_document"]:
        print(f"{row['source']:<48}{row['pages']:>7}{row['words']:>8,}{row['chunks']:>8}")

    print("-" * 71)
    print(f"{'total':<48}{'':>7}{result['words']:>8,}{result['chunks']:>8}")
    print(f"\nStored {result['chunks']} chunks in {settings.QDRANT_PATH}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
