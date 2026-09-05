import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    HnswConfigDiff,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.core.config import settings
from app.services.embedding_service import EmbeddingService

# Qdrant point ids must be an integer or a UUID. Chunk ids are strings
# like "policy-base.md::7", so uuid5 hashes them deterministically -
# re-ingesting a chunk overwrites it instead of duplicating it.
ID_NAMESPACE = uuid.UUID("6f1c9a4e-3f2b-5d7a-9c1e-8b4d2a6f0e35")

# HNSW index tuning. Nobody sweeps these in the comparison scripts, so
# they are fixed constants, not settings - Qdrant's own defaults, written
# out for visibility rather than left implicit.
HNSW_M = 16
HNSW_EF_CONSTRUCT = 100
HNSW_EF_SEARCH = 128


class VectorStore:
    """
    Service responsible for storing and searching vectors in Qdrant.
    """

    def __init__(
        self,
        collection_name: str | None = None,
        embedding_service: EmbeddingService | None = None,
        client: QdrantClient | None = None,
    ):

        self.collection_name = collection_name or settings.COLLECTION_NAME

        self.embedding_service = embedding_service or EmbeddingService()

        self.client = client or QdrantClient(path=settings.QDRANT_PATH)

        # Lazily built, cached until the next rebuild_index() - see
        # search_hybrid() and hybrid_search.BM25Index.
        self._bm25_index = None

    def rebuild_index(self, chunks: list[dict], batch_size: int = 128) -> int:
        """
        Wipe the collection and store these chunks from scratch, so
        re-ingesting never leaves stale chunks behind from documents
        that were removed from data/.
        """

        from app.services.chunk_service import embed_text

        if self.client.collection_exists(self.collection_name):
            # Clear existing points via the delete API rather than
            # delete_collection + create_collection: on Windows,
            # deleting the collection's directory can silently fail
            # (Qdrant swallows the error) if the local storage file is
            # still open in this process, leaving stale points behind
            # after "recreating" the collection - confirmed by testing
            # a re-ingest with a different chunk count than before.
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=Filter(),
            )
        else:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.embedding_service.dimension(),
                    distance=Distance.COSINE,
                ),
                hnsw_config=HnswConfigDiff(
                    m=HNSW_M,
                    ef_construct=HNSW_EF_CONSTRUCT,
                ),
            )

        for start in range(0, len(chunks), batch_size):

            batch = chunks[start:start + batch_size]

            embeddings = self.embedding_service.generate_embeddings(
                [embed_text(chunk) for chunk in batch]
            )

            self.client.upsert(
                collection_name=self.collection_name,
                points=[
                    PointStruct(
                        id=str(uuid.uuid5(ID_NAMESPACE, chunk["chunk_id"])),
                        vector=embedding,
                        payload=chunk,
                    )
                    for chunk, embedding in zip(batch, embeddings)
                ],
            )

        self._bm25_index = None  # invalidate - rebuilt lazily on next hybrid search

        return self.count()

    def count(self) -> int:

        if not self.client.collection_exists(self.collection_name):
            return 0

        return self.client.count(
            collection_name=self.collection_name,
            exact=True,
        ).count

    def search(
        self,
        query_embedding: list[float],
        top_k: int,
        source: str | None = None,
    ) -> list[dict]:
        """
        Search Qdrant and return payloads with their similarity score.
        """

        query_filter = None

        if source:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="source",
                        match=MatchValue(value=source),
                    )
                ]
            )

        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_embedding,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
            search_params={"hnsw_ef": HNSW_EF_SEARCH},
        )

        return [
            {**(point.payload or {}), "score": float(point.score)}
            for point in response.points
        ]

    def get_all_chunks(self) -> list[dict]:
        """
        Every stored chunk's payload, unranked - used to build the
        BM25 index for hybrid search so it always reflects whatever
        was last ingested, whichever chunking strategy produced it.
        """

        if not self.client.collection_exists(self.collection_name):
            return []

        points, _ = self.client.scroll(
            collection_name=self.collection_name,
            limit=100_000,
            with_payload=True,
            with_vectors=False,
        )

        return [point.payload for point in points]

    def search_hybrid(
        self,
        query_embedding: list[float],
        question: str,
        top_k: int,
        source: str | None = None,
    ) -> list[dict]:
        """
        Dense search fused with BM25 keyword search via Reciprocal
        Rank Fusion (k=60) - see app/services/hybrid_search.py. Measured
        in docs/training/week4/results.md before being wired in here.
        """

        from app.services.hybrid_search import BM25Index, fuse_with_rrf

        if self._bm25_index is None:
            self._bm25_index = BM25Index(self.get_all_chunks())

        # Dense ranking over the WHOLE collection, so RRF has a full
        # rank position for every chunk dense search "knows about" -
        # not just the usual top_k window.
        dense_results = self.search(
            query_embedding=query_embedding,
            top_k=self.count(),
            source=source,
        )

        bm25_rank = self._bm25_index.rank(question)

        if source:
            bm25_rank = {
                chunk_id: rank
                for chunk_id, rank in bm25_rank.items()
                if self._bm25_index.chunk_by_id[chunk_id]["source"] == source
            }

        return fuse_with_rrf(
            dense_results,
            bm25_rank,
            self._bm25_index.chunk_by_id,
            top_k=top_k,
        )
