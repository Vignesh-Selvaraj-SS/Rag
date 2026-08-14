from app.core.config import DATA_DIR, settings
from app.services.chunk_service import ChunkService
from app.services.document_loader import DocumentLoader
from app.services.llm_service import LLMService, REFUSAL_MESSAGE
from app.services.retrieval_service import RetrievalService
from app.services.vector_store import VectorStore


class RAGService:
    """
    Service that orchestrates retrieval and generation.
    """

    def __init__(self):

        self.loader = DocumentLoader()
        self.chunk_service = ChunkService()
        self.retriever = RetrievalService()
        self.llm = LLMService()

    def ask(
        self,
        question: str,
        top_k: int | None = None,
        min_score: float | None = None,
        source: str | None = None,
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
    ) -> dict:

        return self.retriever.retrieve(
            question,
            top_k=top_k,
            min_score=min_score,
            source=source,
        )

    def ingest(self) -> dict:
        """
        Rebuild the index from everything in the data folder.
        """

        documents = self.loader.load_directory(DATA_DIR)

        if not documents:
            raise FileNotFoundError(
                f"No .md, .txt or .pdf files found in {DATA_DIR}"
            )

        chunks = self.chunk_service.create_chunks_for_all(documents)

        self.retriever.vector_store.clear_collection()

        self.retriever.vector_store.add_documents(chunks)

        return {
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
