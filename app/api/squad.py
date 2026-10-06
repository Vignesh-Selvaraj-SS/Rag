"""
The claims squad's endpoint (Week 10): run the manager + two specialists on
one adjuster-note input and return the final summary alongside every
agent's own output - the UI trace this system never had when it only
existed as a CLI race script.
"""

import logging

from fastapi import APIRouter

from app.api.deps import SquadDep, SquadRaceDep
from app.core.errors import AppError
from app.schemas.squad import (
    SquadRaceStartRequest,
    SquadRaceStatusResponse,
    SquadRunRequest,
    SquadRunResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/squad", tags=["Claims Squad"])


@router.post("/run", response_model=SquadRunResponse)
def run_squad(request: SquadRunRequest, squad: SquadDep):
    """
    `simulate_coverage_worker_failure` deliberately forces the coverage/
    exclusions worker's hand-off to fail (Week 10's injected-failure
    exercise, see docs/training/week10/failure_case.md) - a checkbox in the
    UI, not just a one-off CLI flag, so the degrade-not-lie behaviour can be
    demonstrated live on any claim, not only the one case the original race
    happened to pick.
    """

    try:
        outcome = squad.process(
            request.notes,
            fail_coverage_worker=request.simulate_coverage_worker_failure,
        )
    except AppError as error:
        logger.warning("Squad run failed: %s", error)
        return {
            "notes": request.notes,
            "summary": None,
            "fields": {},
            "sources": [],
            "handoffs": [],
            "intermediate": {},
            "worker_error": None,
            "tokens_used": 0,
            "cost_usd": 0.0,
            "latency_ms": 0,
            "error": error.message,
        }

    sources = sorted({
        hit["source"]
        for hit in outcome["retrieved"]
        if hit["chunk_id"] in outcome["cited_chunk_ids"]
    })

    return {
        "notes": request.notes,
        "summary": outcome["summary"],
        "fields": outcome["fields"],
        "sources": sources,
        "handoffs": outcome["handoffs"],
        "intermediate": outcome["intermediate"],
        "worker_error": outcome["worker_error"],
        "tokens_used": outcome["tokens_used"],
        "cost_usd": outcome["cost_usd"],
        "latency_ms": outcome["latency_ms"],
        "error": None,
    }


@router.post("/race/start", response_model=SquadRaceStatusResponse)
def start_race(request: SquadRaceStartRequest, race: SquadRaceDep):
    """
    Week 10's full race (the manager + 2 specialists vs. SummaryService,
    over the Week 6 M6 cases) - runs in a background thread, not this
    request, since a full race makes dozens of real Groq calls and takes
    minutes. Returns immediately with the current status; poll GET
    /race/status to watch it progress. 400s if one is already running.
    """

    return race.start(only=request.only, sleep=request.sleep)


@router.get("/race/status", response_model=SquadRaceStatusResponse)
def race_status(race: SquadRaceDep):
    """Cheap to poll - reads the same incrementally-saved results file the background race writes to."""

    return race.status()
