from app.core.config import DATA_DIR, settings
from app.services.chunk_service import CHUNK_STRATEGIES
from app.services.document_loader import load_directory
from app.services.llm_service import LLMService, REFUSAL_MESSAGE
from app.services.retrieval_service import RetrievalService


class RAGService:
    """
    Service that orchestrates retrieval and generation.
    """

    def __init__(self):

        self.retriever = RetrievalService()
        self.llm = LLMService()

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

        if not retrieval["passes_gate"]:
            return {
                "question": question,
                "answer": REFUSAL_MESSAGE,
                "refused": True,
                "refused_by": "gate",
                "sources": [],
                "retrieved": retrieval["hits"],
                "invalid_citations": [],
                "model": "(no model call)",
            }

        result = self.llm.generate_answer(question, retrieval["hits"])

        cited_hits = [
            retrieval["hits"][number - 1]
            for number in result["cited"]
            if 1 <= number <= len(retrieval["hits"])
        ]

        return {
            "question": question,
            "answer": result["answer"],
            "refused": result["refused"],
            "refused_by": "model" if result["refused"] else None,
            "sources": cited_hits,
            "retrieved": retrieval["hits"],
            "invalid_citations": result["invalid_citations"],
            "model": settings.MODEL_NAME,
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
        the named chunking strategy (see CHUNK_STRATEGIES).
        """

        if strategy not in CHUNK_STRATEGIES:
            raise ValueError(
                f"Unknown chunking strategy '{strategy}'. "
                f"Choose from: {', '.join(CHUNK_STRATEGIES)}"
            )

        documents = load_directory(DATA_DIR)

        if not documents:
            raise FileNotFoundError(
                f"No .md, .txt or .pdf files found in {DATA_DIR}"
            )

        chunks = CHUNK_STRATEGIES[strategy](documents)

        self.retriever.vector_store.rebuild_index(chunks)

        return {
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

    def chunk_count(self) -> int:

        return self.retriever.vector_store.count()
