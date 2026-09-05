from fastapi import APIRouter

from app.api.deps import EvaluationDep, RagDep, require_index
from app.schemas.evaluation import (
    EvaluationRun,
    EvaluationRunRequest,
    EvaluationRunSummary,
    GoldenSetResponse,
    GoldenSetUpdate,
    InspectRequest,
    InspectResponse,
)

router = APIRouter(prefix="/api/v1/evaluation", tags=["Evaluation"])


@router.get("/golden-set", response_model=GoldenSetResponse)
def get_golden_set(evaluation: EvaluationDep):
    return {"items": evaluation.load_golden_set()}


@router.put("/golden-set", response_model=GoldenSetResponse)
def update_golden_set(update: GoldenSetUpdate, evaluation: EvaluationDep):
    items = evaluation.save_golden_set([item.model_dump() for item in update.items])
    return {"items": items}


@router.post("/runs", response_model=EvaluationRun)
def run_evaluation(request: EvaluationRunRequest, evaluation: EvaluationDep, rag: RagDep):
    """
    Retrieve every golden-set question with the chosen mode against the
    live index and report hit-rate@3, hit-rate@5, MRR and p50 latency.
    No answers are generated.
    """

    require_index(rag)

    return evaluation.run(
        retriever=rag.retriever,
        mode=request.mode,
        index_metadata=rag.index_metadata.read(),
        top_k=request.top_k,
        label=request.label,
    )


@router.get("/runs", response_model=list[EvaluationRunSummary])
def list_runs(evaluation: EvaluationDep):
    return evaluation.list_runs()


@router.get("/runs/{run_id}", response_model=EvaluationRun)
def get_run(run_id: str, evaluation: EvaluationDep):
    return evaluation.get_run(run_id)


@router.delete("/runs/{run_id}", status_code=204)
def delete_run(run_id: str, evaluation: EvaluationDep):
    evaluation.delete_run(run_id)


@router.post("/inspect", response_model=InspectResponse)
def inspect_question(request: InspectRequest, evaluation: EvaluationDep, rag: RagDep):
    """
    Run one golden-set question through the full pipeline and show what was
    retrieved next to the generated answer, marking the expected chunk.
    """

    require_index(rag)

    return evaluation.inspect(rag, request.question_id, request.mode)
