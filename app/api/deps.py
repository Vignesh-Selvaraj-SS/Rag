"""
FastAPI dependencies. Routers depend on these providers rather than on the
concrete instances so tests can swap in fakes with `app.dependency_overrides`.
"""

from typing import Annotated

from fastapi import Depends

from app.core.errors import IndexEmptyError
from app.services import shared
from app.services.agent_service import ClaimAgent
from app.services.claims_squad_service import ClaimsSquadService
from app.services.document_service import DocumentService
from app.services.evaluation_service import EvaluationService
from app.services.fixed_claim_workflow import FixedClaimWorkflow
from app.services.rag_service import RAGService
from app.services.squad_race_service import SquadRaceService
from app.services.trace_service import TraceService


def rag_service() -> RAGService:
    return shared.get_rag_service()


def document_service() -> DocumentService:
    return shared.get_document_service()


def trace_service() -> TraceService:
    return shared.get_trace_service()


def evaluation_service() -> EvaluationService:
    return shared.get_evaluation_service()


def agent() -> ClaimAgent:
    return shared.get_agent()


def fixed_workflow() -> FixedClaimWorkflow:
    return shared.get_fixed_workflow()


def squad_service() -> ClaimsSquadService:
    return shared.get_claims_squad_service()


def squad_race_service() -> SquadRaceService:
    return shared.get_squad_race_service()


RagDep = Annotated[RAGService, Depends(rag_service)]
DocumentsDep = Annotated[DocumentService, Depends(document_service)]
TracesDep = Annotated[TraceService, Depends(trace_service)]
EvaluationDep = Annotated[EvaluationService, Depends(evaluation_service)]
AgentDep = Annotated[ClaimAgent, Depends(agent)]
FixedWorkflowDep = Annotated[FixedClaimWorkflow, Depends(fixed_workflow)]
SquadDep = Annotated[ClaimsSquadService, Depends(squad_service)]
SquadRaceDep = Annotated[SquadRaceService, Depends(squad_race_service)]


def require_index(rag: RAGService) -> None:

    if rag.chunk_count() == 0:
        raise IndexEmptyError()
