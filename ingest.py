"""
Build the search index from the documents in data/.

    python ingest.py
    python ingest.py --strategy fixed_size
"""

import argparse

from app.core.config import settings
from app.services.shared import rag_service


def main() -> int:

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--strategy",
        choices=["heading", "fixed_size"],
        default="heading",
    )
    args = parser.parse_args()

    print(f"Embedding with {settings.EMBEDDING_MODEL} (strategy: {args.strategy}) ...")

    result = rag_service.ingest(strategy=args.strategy)

    print(f"\n{'document':<48}{'pages':>7}{'words':>8}{'chunks':>8}")
    print("-" * 71)

    for row in result["per_document"]:
        print(
            f"{row['source']:<48}{row['pages']:>7}"
            f"{row['words']:>8,}{row['chunks']:>8}"
        )

    print("-" * 71)
    print(f"{'total':<48}{'':>7}{result['words']:>8,}{result['chunks']:>8}")
    print(f"\nStored {result['chunks']} chunks in {settings.QDRANT_PATH}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
