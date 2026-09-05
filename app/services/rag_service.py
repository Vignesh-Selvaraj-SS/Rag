import logging

from app.core.config import DATA_DIR, settings
from app.core.errors import BadRequestError
from app.services.chunk_service import CHUNK_STRATEGIES
from app.services.document_loader import load_directory
from app.services.index_metadata import IndexMetadata
from app.services.llm_service import (
    LLMService,
    MAX_TOKENS,
    PROMPT_VERSION,
    REFUSAL_MESSAGE,
    TEMPERATURE,
)
from app.services.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)


class RAGService:
    """
    Orchestrates retrieval, generation and index building.
    """

    def __init__(
        self,
        retriever: RetrievalService | None = None,
        llm: LLMService | None = None,
        index_metadata: IndexMetadata | None = None,
    ):

        self.retriever = retriever or RetrievalService()
        self.llm = llm or LLMService()
        self.index_metadata = index_metadata or IndexMetadata(settings.index_metadata_path)

    def ask(
        self,
        question: str,
        top_k: int | None = None,
        min_score: float | None = None,
        source: str | None = None,
        mode: str = "dense",
    ) -> dict:
        """
        Retrieve chunks, then generate an answer citing only what it
        actually used. `sources` is what the answer cited; `retrieved`
        is everything the model was shown - the two are not the same,
        and returning only the second would hide a fabricated citation.
        """

        retrieval = self.retriever.retrieve(
            question,
            top_k=top_k,
            min_score=min_score,
            source=source,
            mode=mode,
        )

        # Resolved rather than requested, so a trace records the values the
        # run actually used even when the caller passed nothing.
        params = {
            "mode": mode,
            "top_k": settings.TOP_K if top_k is None else top_k,
            "min_score": settings.MIN_SCORE if min_score is None else min_score,
            "source_filter": source,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
        }

        common = {
            "question": question,
            "retrieved": retrieval["hits"],
            "best_score": retrieval["best_score"],
            "passes_gate": retrieval["passes_gate"],
            "params": params,
        }

        if not retrieval["passes_gate"]:
            return {
                **common,
                "answer": REFUSAL_MESSAGE,
                "refused": True,
                "refused_by": "gate",
                "sources": [],
                "invalid_citations": [],
                "model": "(no model call)",
                "prompt_version": PROMPT_VERSION,
                "raw_output": None,
            }

        result = self.llm.generate_answer(question, retrieval["hits"])

        cited_hits = [
            retrieval["hits"][number - 1]
            for number in result["cited"]
            if 1 <= number <= len(retrieval["hits"])
        ]

        return {
            **common,
            "answer": result["answer"],
            "refused": result["refused"],
            "refused_by": "model" if result["refused"] else None,
            "sources": cited_hits,
            "invalid_citations": result["invalid_citations"],
            "model": settings.MODEL_NAME,
            "prompt_version": result["prompt_version"],
            "raw_output": result["raw_output"],
        }

    def search(
        self,
        question: str,
        top_k: int | None = None,
        min_score: float | None = None,
        source: str | None = None,
        mode: str = "dense",
    ) -> dict:

        return self.retriever.retrieve(
            question,
            top_k=top_k,
            min_score=min_score,
            source=source,
            mode=mode,
        )

    def ingest(self, strategy: str = "heading") -> dict:
        """
        Rebuild the index from everything in the data folder, using
        the named chunking strategy (see CHUNK_STRATEGIES), and record
        what was built in the index metadata.
        """

        if strategy not in CHUNK_STRATEGIES:
            raise BadRequestError(
                f"Unknown chunking strategy '{strategy}'. "
                f"Choose from: {', '.join(CHUNK_STRATEGIES)}."
            )

        documents = load_directory(DATA_DIR)

        if not documents:
            raise BadRequestError(
                "No supported documents (.pdf, .md, .txt) were found. Upload one first."
            )

        chunks = CHUNK_STRATEGIES[strategy](documents)

        logger.info(
            "Rebuilding index: %d documents, %d chunks, strategy=%s",
            len(documents), len(chunks), strategy,
        )

        self.retriever.vector_store.rebuild_index(chunks)

        result = {
            "strategy": strategy,
            "documents": len(documents),
            "words": sum(document["word_count"] for document in documents),
            "chunks": len(chunks),
            "per_document": [
                {
                    "source": document["source"],
                    "pages": len(document["pages"]),
                    "words": document["word_count"],
                    "chunks": sum(
                        1 for chunk in chunks
                        if chunk["source"] == document["source"]
                    ),
                }
                for document in documents
            ],
        }

        metadata = self.index_metadata.write(result)

        return {**result, "built_at": metadata["built_at"]}

    def chunk_count(self) -> int:

        return self.retriever.vector_store.count()

    def index_status(self) -> dict:

        metadata = self.index_metadata.read()
        chunks = self.chunk_count()

        return {
            "chunks": chunks,
            "ready": chunks > 0,
            "strategy": metadata["strategy"] if metadata else None,
            "built_at": metadata["built_at"] if metadata else None,
            "documents": metadata["documents"] if metadata else None,
            "words": metadata["words"] if metadata else None,
            "collection": settings.COLLECTION_NAME,
            "embedding_model": settings.EMBEDDING_MODEL,
        }
