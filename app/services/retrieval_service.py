from app.core.config import settings
from app.services.chunk_service import page_label
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore

# For "rerank"/"mmr" modes: how many dense candidates to fetch before
# narrowing down to top_k. Wide enough that the right chunk is likely
# in the pool even if it wasn't ranked in the final top_k by dense
# search alone; narrow enough that reranking (which reads every
# candidate individually) stays affordable.
CANDIDATE_POOL_SIZE = 25


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
        mode: str = "dense",
    ) -> dict:

        top_k = settings.TOP_K if top_k is None else top_k

        min_score = settings.MIN_SCORE if min_score is None else min_score

        # Query transforms happen before embedding, not before search -
        # "rewrite" and "hyde" both change WHAT gets embedded, then
        # still run a normal dense search with that embedding.
        search_text = question

        if mode == "rewrite":
            from app.services.query_transform import rewrite_query
            search_text = rewrite_query(question)

        elif mode == "hyde":
            from app.services.query_transform import generate_hyde_passage
            search_text = generate_hyde_passage(question)

        query_embedding = self.embedding_service.generate_query_embedding(
            search_text
        )

        if mode == "hybrid":
            results = self.vector_store.search_hybrid(
                query_embedding=query_embedding,
                question=search_text,
                top_k=top_k,
                source=source,
            )

        elif mode == "rerank":
            from app.services.reranker import rerank
            candidates = self.vector_store.search(
                query_embedding=query_embedding,
                top_k=CANDIDATE_POOL_SIZE,
                source=source,
            )
            results = rerank(question, candidates, top_k)

        elif mode == "mmr":
            from app.services.mmr import mmr_select
            candidates = self.vector_store.search(
                query_embedding=query_embedding,
                top_k=CANDIDATE_POOL_SIZE,
                source=source,
            )
            results = mmr_select(query_embedding, candidates, self.embedding_service, top_k)

        else:
            # "dense", "rewrite" and "hyde" all end up here - the two
            # transforms only changed search_text/query_embedding above,
            # the actual search itself is plain dense search.
            results = self.vector_store.search(
                query_embedding=query_embedding,
                top_k=top_k,
                source=source,
            )

        hits = []

        for result in results:

            page_start = result.get("page_start", 1)
            page_end = result.get("page_end", page_start)

            hits.append(
                {
                    "text": result.get("text", ""),
                    "source": result.get("source", "unknown"),
                    "heading": result.get("heading", ""),
                    "page_start": page_start,
                    "page_end": page_end,
                    "page": page_label(page_start, page_end),
                    "score": result["score"],
                    "dense_score": result.get("dense_score", result["score"]),
                }
            )

        # The gate compares against MIN_SCORE, a cosine-similarity
        # threshold - hybrid mode's "score" is a fused RRF value on a
        # different scale, so the gate uses "dense_score" instead,
        # which keeps its real meaning regardless of ranking mode.
        best_dense_score = hits[0]["dense_score"] if hits else 0.0

        return {
            "question": question,
            "hits": hits,
            "best_score": hits[0]["score"] if hits else 0.0,
            "passes_gate": bool(hits) and best_dense_score >= min_score,
            "min_score": min_score,
        }