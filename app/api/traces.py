from fastapi import APIRouter, Query

from app.api.deps import RagDep, TracesDep, require_index
from app.schemas.traces import (
    ReplayResponse,
    TraceDetail,
    TraceListResponse,
    TraceSampleResponse,
    TraceStats,
)

router = APIRouter(prefix="/api/v1/traces", tags=["Traces"])


@router.get("", response_model=TraceListResponse)
def list_traces(
    traces: TracesDep,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    refused: bool | None = None,
    mode: str | None = Query(default=None, max_length=20),
    search: str | None = Query(default=None, max_length=200),
):
    return traces.list(limit=limit, offset=offset, refused=refused, mode=mode, search=search)


@router.get("/stats", response_model=TraceStats)
def trace_stats(traces: TracesDep):
    return traces.stats()


@router.get("/sample", response_model=TraceSampleResponse)
def sample_traces(
    traces: TracesDep,
    seed: int = Query(ge=0),
    n: int = Query(default=20, ge=1, le=200),
):
    """
    A seeded random sample of traces for manual review. The same seed always
    yields the same sample.
    """

    return traces.sample(seed=seed, n=n)


@router.get("/{trace_id}", response_model=TraceDetail)
def get_trace(trace_id: str, traces: TracesDep):
    return traces.get(trace_id)


@router.post("/{trace_id}/replay", response_model=ReplayResponse)
def replay_trace(trace_id: str, traces: TracesDep, rag: RagDep):
    """
    Re-run a recorded trace: retrieval with its recorded parameters, and
    generation from the chunks stored in the trace. Reports what changed.
    """

    require_index(rag)

    return traces.replay(trace_id, rag)
