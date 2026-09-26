"""
FastAPI dependencies. Routers depend on these providers rather than on the
concrete instances so tests can swap in fakes with `app.dependency_overrides`.
"""

from typing import Annotated

from fastapi import Depends

from app.core.errors import IndexEmptyError
from app.services import shared
from app.services.agent_service import ClaimAgent
from app.services.document_service import DocumentService
from app.services.evaluation_service import EvaluationService
from app.services.fixed_claim_workflow import FixedClaimWorkflow
from app.services.fixed_triage_workflow import FixedClaimTriageWorkflow
from app.services.rag_service import RAGService
from app.services.trace_service import TraceService
from app.services.triage_agent import ClaimTriageAgent


def rag_service() -> RAGService:
    return shared.get_rag_service()


def document_service() -> DocumentService:
    return shared.get_document_service()


def trace_service() -> TraceService:
    return shared.get_trace_service()


def evaluation_service() -> EvaluationService:
    return shared.get_evaluation_service()


def triage_agent() -> ClaimTriageAgent:
    return shared.get_triage_agent()


def fixed_triage_workflow() -> FixedClaimTriageWorkflow:
    return shared.get_fixed_triage_workflow()


def policy_agent() -> ClaimAgent:
    return shared.get_policy_agent()


def fixed_policy_workflow() -> FixedClaimWorkflow:
    return shared.get_fixed_policy_workflow()


RagDep = Annotated[RAGService, Depends(rag_service)]
DocumentsDep = Annotated[DocumentService, Depends(document_service)]
TracesDep = Annotated[TraceService, Depends(trace_service)]
EvaluationDep = Annotated[EvaluationService, Depends(evaluation_service)]
TriageAgentDep = Annotated[ClaimTriageAgent, Depends(triage_agent)]
FixedTriageWorkflowDep = Annotated[FixedClaimTriageWorkflow, Depends(fixed_triage_workflow)]
PolicyAgentDep = Annotated[ClaimAgent, Depends(policy_agent)]
FixedPolicyWorkflowDep = Annotated[FixedClaimWorkflow, Depends(fixed_policy_workflow)]


def require_index(rag: RAGService) -> None:

    if rag.chunk_count() == 0:
        raise IndexEmptyError()
