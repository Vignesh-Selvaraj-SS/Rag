"""
Week 11 Task Set D: proper per-request logging for claim-summary runs
(SummaryService), so a specific past answer can be found from a vague
complaint alone - no trace id, no claim number, no timestamp.

This is deliberately a separate log from app/services/trace_service.py
(the Week 5 chat trace), not an extension of it: chat traces are shaped
around a refused/answered policy question, with no concept of a coverage
decision, a claim number, or multiple cost-bearing spans. Reuses that
module's redaction primitives (redact/scrub/collect_identifiers) rather
than re-deriving them - the same PII rules apply regardless of which
pipeline produced the text.

What earlier logging in this app was missing, closed here:
  - cost and tokens per request - previously tracked nowhere at all for
    the chat pipeline, and only as one lump total for the agent/squad
  - per-span breakdown (retrieval vs generation), not one lump latency
  - retrieved context ids, so a wrong coverage call can be told apart
    from "retrieval missed the exclusion" vs "the model ignored it"
  - the ANSWER is indexed for search, not just the question - searching
    only the input is why a complaint describing the output ("said it
    was covered") used to be unfindable without reading every entry
"""

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.errors import NotFoundError
from app.services.trace_service import redact, scrub, collect_identifiers

logger = logging.getLogger(__name__)


def new_request_id() -> str:
    return f"r_{uuid.uuid4().hex[:12]}"


def classify_input_type(notes: str) -> str:
    """
    A cheap, deterministic slice dimension - no model call. Real adjuster
    notes in this app's fixture set are always a coverage question about
    one claim; this exists so "input type" is a genuine, usable slice
    rather than a constant every request shares.
    """

    lowered = (notes or "").lower()
    if "denied" in lowered or "denial" in lowered:
        return "denial_review"
    if "deductible" in lowered and "coverage" not in lowered:
        return "deductible_only"
    return "coverage_question"


def build_claim_log_entry(
    request_id: str,
    notes: str,
    claim_no: str | None,
    outcome: dict,
    origin: str = "single_agent",
    timestamp: str | None = None,
) -> dict:
    """
    One request, fully redacted before it is ever written to disk -
    `outcome` is SummaryService.summarise()'s (or an equivalent pipeline's)
    return dict: must carry `summary`, `fields`, `retrieved`,
    `cited_chunk_ids`, `spans`, `tokens_used`, `cost_usd`, `latency_ms`,
    and a `*_prompt_version` key.
    """

    identifiers = collect_identifiers(notes)
    prompt_version = outcome.get("summary_prompt_version") or outcome.get("squad_prompt_version")

    return {
        "request_id": request_id,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "origin": origin,
        "input_type": classify_input_type(notes),
        "prompt_version": prompt_version,
        "claim_no": redact(claim_no),
        "notes_redacted": scrub(notes, identifiers),
        "fields": {key: scrub(value, identifiers) for key, value in (outcome.get("fields") or {}).items()},
        "summary_redacted": scrub(outcome.get("summary"), identifiers),
        "retrieved_context_ids": [hit["chunk_id"] for hit in outcome.get("retrieved", [])],
        "cited_chunk_ids": outcome.get("cited_chunk_ids", []),
        "spans": outcome.get("spans", []),
        # Week 11 canary (see docs/training/week11/task_set_d.md): non-empty
        # here means the primary search missed a named endorsement and the
        # retrieval-layer fix had to top it up. Rare is healthy; a rising
        # rate means ranking is degrading, not that the fix is "working
        # harder" - it is the thing to alert on, not celebrate.
        "endorsements_topped_up": outcome.get("endorsements_topped_up", []),
        "tokens_used": outcome.get("tokens_used", 0),
        "cost_usd": outcome.get("cost_usd", 0.0),
        "latency_ms": outcome.get("latency_ms", 0),
    }


class ClaimLogService:
    """Append-only JSONL store for claim-summary requests, plus the slices the drill needs."""

    def __init__(self, path: Path, enabled: bool = True):
        self.path = path
        self.enabled = enabled
        self._lock = threading.Lock()

    # ----------------------------------------------------------------- write

    def record(
        self,
        notes: str,
        claim_no: str | None,
        outcome: dict,
        origin: str = "single_agent",
        timestamp: str | None = None,
    ) -> str | None:

        if not self.enabled:
            return None

        entry = build_claim_log_entry(
            request_id=new_request_id(),
            notes=notes,
            claim_no=claim_no,
            outcome=outcome,
            origin=origin,
            timestamp=timestamp,
        )

        try:
            self.append(entry)
        except OSError:
            logger.exception("Could not write claim log entry %s", entry["request_id"])
            return None

        return entry["request_id"]

    def append(self, entry: dict) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ read

    def load_all(self) -> list[dict]:

        if not self.path.exists():
            return []

        entries = []
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("Skipping unreadable claim log line")

        return entries

    def get(self, request_id: str) -> dict:

        for entry in self.load_all():
            if entry["request_id"] == request_id:
                return entry

        raise NotFoundError(f"No claim log entry with id '{request_id}'.")

    # ----------------------------------------------------------- the slices

    def by_time(self, start: str | None = None, end: str | None = None) -> list[dict]:
        entries = self.load_all()
        if start:
            entries = [e for e in entries if e["timestamp"] >= start]
        if end:
            entries = [e for e in entries if e["timestamp"] <= end]
        return sorted(entries, key=lambda e: e["timestamp"])

    def by_prompt_version(self, version: str) -> list[dict]:
        return [e for e in self.load_all() if e.get("prompt_version") == version]

    def by_input_type(self, input_type: str) -> list[dict]:
        return [e for e in self.load_all() if e.get("input_type") == input_type]

    def cost_outliers(self, n: int = 5) -> list[dict]:
        return sorted(self.load_all(), key=lambda e: e.get("cost_usd", 0.0), reverse=True)[:n]

    def search_output(self, needle: str) -> list[dict]:
        """
        Searches the ANSWER (summary + individual fields), not the question -
        the slice a complaint describing what the system SAID requires.
        trace_service.TraceService.list()'s `search` only ever indexed the
        question; this is the "both have to be indexed" fix for this log.
        """

        needle_lower = needle.lower()
        hits = []
        for entry in self.load_all():
            haystack = " ".join([
                entry.get("summary_redacted") or "",
                " ".join(str(v) for v in (entry.get("fields") or {}).values() if v),
            ]).lower()
            if needle_lower in haystack:
                hits.append(entry)
        return hits
