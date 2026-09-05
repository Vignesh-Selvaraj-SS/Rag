import time

from fastapi import APIRouter

from app.api.deps import RagDep, TracesDep, require_index
from app.schemas.chat import ChatRequest, ChatResponse, SearchRequest, SearchResponse

router = APIRouter(prefix="/api/v1", tags=["Chat"])


def _chunk_view(hits: list[dict]) -> list[dict]:
    return [
        {
            "rank": rank,
            "chunk_id": hit["chunk_id"],
            "source": hit["source"],
            "heading": hit["heading"],
            "page": hit["page"],
            "score": round(float(hit["score"]), 4),
            "dense_score": round(float(hit["dense_score"]), 4),
            "text": hit["text"],
        }
        for rank, hit in enumerate(hits, start=1)
    ]


# Plain `def` on purpose: retrieval and generation are blocking calls, so
# FastAPI runs these handlers in its thread pool instead of on the event loop.


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, rag: RagDep, traces: TracesDep):
    """
    Answer a question from the indexed documents. `sources` lists only the
    chunks the answer actually cited. Set `include_debug` to also receive
    everything the model was shown, the resolved parameters and the raw output.
    """

    require_index(rag)

    started = time.perf_counter()

    result = rag.ask(
        request.question,
        top_k=request.top_k,
        min_score=request.min_score,
        source=request.source,
        mode=request.mode,
    )

    latency_ms = int((time.perf_counter() - started) * 1000)

    index = rag.index_metadata.read()

    trace_id = traces.record(
        question=request.question,
        result=result,
        latency_ms=latency_ms,
        chunk_strategy=index["strategy"] if index else None,
    )

    rank_by_chunk = {hit["chunk_id"]: rank for rank, hit in enumerate(result["retrieved"], start=1)}

    response = {
        "answer": result["answer"],
        "sources": [
            {
                "rank": rank_by_chunk.get(hit["chunk_id"], 0),
                "chunk_id": hit["chunk_id"],
                "source": hit["source"],
                "heading": hit["heading"],
                "page": hit["page"],
            }
            for hit in result["sources"]
        ],
        "refused": result["refused"],
        "refused_by": result["refused_by"],
        "mode": request.mode,
        "latency_ms": latency_ms,
        "trace_id": trace_id,
        "debug": None,
    }

    if request.include_debug:
        response["debug"] = {
            "retrieved": _chunk_view(result["retrieved"]),
            "params": result["params"],
            "model": result["model"],
            "prompt_version": result["prompt_version"],
            "passes_gate": result["passes_gate"],
            "best_score": round(float(result["best_score"]), 4),
            "invalid_citations": result["invalid_citations"],
            "raw_output": result["raw_output"],
        }

    return response


@router.post("/search", response_model=SearchResponse)
def search(request: SearchRequest, rag: RagDep):
    """
    Retrieval only - no answer is generated. Shows which chunks a question
    would surface, with their scores and whether the similarity gate passes.
    """

    require_index(rag)

    started = time.perf_counter()

    retrieval = rag.search(
        request.question,
        top_k=request.top_k,
        min_score=request.min_score,
        source=request.source,
        mode=request.mode,
    )

    return {
        "question": request.question,
        "hits": _chunk_view(retrieval["hits"]),
        "best_score": round(float(retrieval["best_score"]), 4),
        "passes_gate": retrieval["passes_gate"],
        "min_score": retrieval["min_score"],
        "mode": request.mode,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }
