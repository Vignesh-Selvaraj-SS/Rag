from app.core.config import settings
from app.services.chunk_service import page_label
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore


class RetrievalService:
    """
    Service responsible for retrieving relevant chunks for a question.

    A score threshold alone cannot decide what to refuse: the worst
    genuine question here scores 0.662 and the worst out-of-scope
    question scores 0.696, so the ranges overlap. The gate below only
    catches questions from a different domain, cheaply. The real
    refusal happens in llm_service, which can actually read the text.
    """

    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
        vector_store: VectorStore | None = None,
    ):

        self.embedding_service = embedding_service or EmbeddingService()

        self.vector_store = vector_store or VectorStore(
            embedding_service=self.embedding_service
        )

    def retrieve(
        self,
        question: str,
        top_k: int | None = None,
        min_score: float | None = None,
        source: str | None = None,
    ) -> dict:

        top_k = settings.TOP_K if top_k is None else top_k

        min_score = settings.MIN_SCORE if min_score is None else min_score

        query_embedding = self.embedding_service.generate_query_embedding(
            question
        )

        results = self.vector_store.search(
            query_embedding=query_embedding,
            top_k=top_k,
            source=source,
        )

        hits = [self._to_hit(result) for result in results]

        best_score = hits[0]["score"] if hits else 0.0

        return {
            "question": question,
            "hits": hits,
            "best_score": best_score,
            "passes_gate": bool(hits) and best_score >= min_score,
            "min_score": min_score,
        }

    @staticmethod
    def _to_hit(result: dict) -> dict:

        page_start = result.get("page_start", 1)
        page_end = result.get("page_end", page_start)

        return {
            "text": result.get("text", ""),
            "source": result.get("source", "unknown"),
            "heading": result.get("heading", ""),
            "page_start": page_start,
            "page_end": page_end,
            "page": page_label(page_start, page_end),
            "score": result["score"],
        }
