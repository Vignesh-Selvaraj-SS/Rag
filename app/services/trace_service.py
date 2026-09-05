"""
Record one complete, replayable trace per answered question, and read them
back for analytics, inspection and replay.

Claimant identifiers are redacted in `build_trace`, before the record is
serialised - the unredacted string never reaches the file. Redacting the
file afterwards would leave the raw names on disk in between, which is the
exposure this is meant to prevent.

Consolidated from the Week 5 tooling (trace_logger, sample, replay).
"""

import difflib
import json
import logging
import random
import re
import statistics
import threading
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.core.errors import NotFoundError
from app.services.trace_checks import run_checks, summarise_checks

logger = logging.getLogger(__name__)

# A forename+surname pair. Two title-case words is the whole shape - form
# codes ("HO-2026-01") and single-letter coverages ("Coverage C") cannot match.
NAME = r"[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})+"

# Names are matched by TRIGGER, never by shape alone: every pattern below uses
# a lookbehind or lookahead so only the name is replaced and the surrounding
# words survive. Shape-only matching would redact headings like "Water Backup"
# out of the retrieved chunk text.
REDACTIONS = [
    (re.compile(r"\bCLM[- ]?\d{4,}\b", re.IGNORECASE), "[CLAIM_NO]"),
    (re.compile(r"\bHO[- ]?\d{7,}\b", re.IGNORECASE), "[POLICY_NO]"),
    (re.compile(r"\bclaim(?:ant)?\s+(?:number\s+)?#?\s*\d{4,}\b", re.IGNORECASE), "[CLAIM_NO]"),
    # "claimant Maria Delgado", "policyholder Robert Chen", "insured Priya Raghavan".
    # The (?i:...) scope keeps the trigger case-insensitive while NAME stays
    # case-SENSITIVE - a global IGNORECASE would let NAME match lowercase prose
    # such as "the insured was aware of it".
    (re.compile(rf"(?<=(?i:claimant )){NAME}"), "[CLAIMANT]"),
    (re.compile(rf"(?<=(?i:policyholder )){NAME}"), "[CLAIMANT]"),
    (re.compile(rf"(?<=(?i:insured )){NAME}"), "[CLAIMANT]"),
    # "Priya Raghavan (claim ...", "Sandra Whitfield, policy ..."
    (re.compile(rf"{NAME}(?=\s*[,(]\s*(?i:claim|policy)\b)"), "[CLAIMANT]"),
    # "for Robert Chen - his air conditioner". The trailing dash or possessive
    # is required: without it, "for Water Backup." in chunk text would match.
    (
        re.compile(rf"(?<=for ){NAME}(?=\s*[-—]\s|\s+(?:his|her|their)\b)"),
        "[CLAIMANT]",
    ),
]


def redact(text: str | None) -> str | None:
    """
    Strip claimant names, claim numbers and policy numbers from free text.
    Called on every field that can carry them, before the trace is written.
    """

    if not text:
        return text

    for pattern, replacement in REDACTIONS:
        text = pattern.sub(replacement, text)

    return text


def collect_identifiers(text: str | None) -> list[tuple[str, str]]:
    """
    The literal identifiers the patterns found, longest first.

    Pattern matching alone is not enough: the model is asked the real
    question, so it can echo a claimant name back in a shape no trigger
    covers - "the deductible for Maria Delgado's claim is $500" has neither
    a preceding "claimant" nor a following ", claim". Whatever the question
    revealed is therefore scrubbed from the answer by value, not by shape.
    """

    if not text:
        return []

    found = []

    for pattern, replacement in REDACTIONS:
        for match in pattern.finditer(text):
            found.append((match.group(0), replacement))

    return sorted(set(found), key=lambda pair: len(pair[0]), reverse=True)


def scrub(text: str | None, identifiers: list[tuple[str, str]]) -> str | None:
    """Remove known identifier literals, then apply the shape patterns."""

    if not text:
        return text

    for literal, replacement in identifiers:
        text = text.replace(literal, replacement)

        # Possessive and split forms: "Delgado's", or just the surname alone
        # once the forename has already gone.
        for word in literal.split():
            if len(word) > 3 and word[0].isupper():
                text = re.sub(rf"\b{re.escape(word)}\b('s|’s)?", replacement, text)

    # Forename and surname replaced separately leave "[CLAIMANT] [CLAIMANT]".
    text = re.sub(r"\[CLAIMANT\](?:\s*\[CLAIMANT\])+", "[CLAIMANT]", text)

    return redact(text)


def new_trace_id() -> str:
    return f"t_{uuid.uuid4().hex[:12]}"


def build_trace(
    trace_id: str,
    question: str,
    result: dict,
    latency_ms: int,
    chunk_strategy: str | None,
    origin: str = "chat",
) -> dict:
    """
    Assemble one trace. Everything needed to replay the run is stored:
    prompt version, retrieved chunk_ids with scores, model, resolved
    params, and the raw model output before parsing.
    """

    identifiers = collect_identifiers(question)

    return {
        "trace_id": trace_id,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "origin": origin,
        "question": redact(question),
        "identifiers_redacted": len(identifiers),
        "model": result["model"],
        "prompt_version": result["prompt_version"],
        "params": result["params"],
        "chunk_strategy": chunk_strategy,
        "retrieved": [
            {
                "rank": rank,
                "chunk_id": hit["chunk_id"],
                "source": hit["source"],
                "heading": hit["heading"],
                "page": hit["page"],
                "score": round(float(hit["score"]), 4),
                "dense_score": round(float(hit["dense_score"]), 4),
                "text": scrub(hit["text"], identifiers),
            }
            for rank, hit in enumerate(result["retrieved"], start=1)
        ],
        "passes_gate": not (result["refused"] and result["refused_by"] == "gate"),
        "raw_output": scrub(result["raw_output"], identifiers),
        "answer": scrub(result["answer"], identifiers),
        "cited_chunk_ids": [hit["chunk_id"] for hit in result["sources"]],
        "invalid_citations": result["invalid_citations"],
        "refused": result["refused"],
        "refused_by": result["refused_by"],
        "latency_ms": latency_ms,
    }


class TraceService:
    """
    Append-only JSONL store plus the read-side operations the UI needs.
    The file is small (one line per question) so it is read in full on
    demand rather than indexed.
    """

    def __init__(self, path: Path, enabled: bool = True):

        self.path = path
        self.enabled = enabled
        self._lock = threading.Lock()

    # ----------------------------------------------------------------- write

    def record(
        self,
        question: str,
        result: dict,
        latency_ms: int,
        chunk_strategy: str | None,
        origin: str = "chat",
    ) -> str | None:

        if not self.enabled:
            return None

        trace = build_trace(
            trace_id=new_trace_id(),
            question=question,
            result=result,
            latency_ms=latency_ms,
            chunk_strategy=chunk_strategy,
            origin=origin,
        )

        try:
            self.append(trace)
        except OSError:
            logger.exception("Could not write trace %s", trace["trace_id"])
            return None

        return trace["trace_id"]

    def append(self, trace: dict) -> None:

        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(trace, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ read

    def load_all(self) -> list[dict]:

        if not self.path.exists():
            return []

        traces = []

        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    traces.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("Skipping unreadable trace line")

        return traces

    def get(self, trace_id: str) -> dict:

        for trace in self.load_all():
            if trace["trace_id"] == trace_id:
                return self.with_checks(trace)

        raise NotFoundError(f"No trace with id '{trace_id}'.")

    def list(
        self,
        limit: int = 50,
        offset: int = 0,
        refused: bool | None = None,
        mode: str | None = None,
        search: str | None = None,
    ) -> dict:

        traces = self.load_all()

        if refused is not None:
            traces = [t for t in traces if bool(t.get("refused")) == refused]

        if mode:
            traces = [t for t in traces if t.get("params", {}).get("mode") == mode]

        if search:
            needle = search.lower()
            traces = [t for t in traces if needle in (t.get("question") or "").lower()]

        traces.sort(key=lambda t: t.get("timestamp", ""), reverse=True)

        page = traces[offset:offset + limit]

        return {
            "total": len(traces),
            "items": [summarise_trace(t) for t in page],
        }

    def sample(self, seed: int, n: int) -> dict:
        """
        Seeded random sample of trace ids. Re-running with the same seed
        gives the same set, which is what makes a reviewed sample provable
        rather than merely claimed.
        """

        traces = self.load_all()

        frame = sorted(trace["trace_id"] for trace in traces)
        size = min(n, len(frame))

        selected = sorted(random.Random(seed).sample(frame, size)) if size else []
        by_id = {trace["trace_id"]: trace for trace in traces}

        return {
            "seed": seed,
            "frame": len(frame),
            "selected": size,
            "items": [summarise_trace(by_id[trace_id]) for trace_id in selected],
        }

    def stats(self) -> dict:

        traces = self.load_all()

        total = len(traces)
        refused = [t for t in traces if t.get("refused")]
        answered = [t for t in traces if not t.get("refused")]
        latencies = sorted(t.get("latency_ms", 0) for t in traces)

        check_summary = Counter()
        for trace in traces:
            check_summary[summarise_checks(run_checks(trace))] += 1

        sources = Counter()
        for trace in traces:
            for chunk_id in trace.get("cited_chunk_ids", []):
                sources[chunk_id.split("::")[0]] += 1

        by_day = Counter(t.get("timestamp", "")[:10] for t in traces if t.get("timestamp"))

        return {
            "total": total,
            "answered": len(answered),
            "refused": len(refused),
            "refused_by_gate": sum(1 for t in refused if t.get("refused_by") == "gate"),
            "refused_by_model": sum(1 for t in refused if t.get("refused_by") == "model"),
            "answered_without_citation": sum(1 for t in answered if not t.get("cited_chunk_ids")),
            "with_invalid_citations": sum(1 for t in traces if t.get("invalid_citations")),
            "identifiers_redacted": sum(t.get("identifiers_redacted", 0) for t in traces),
            "latency_p50_ms": _percentile(latencies, 50),
            "latency_p95_ms": _percentile(latencies, 95),
            "latency_avg_ms": round(statistics.mean(latencies)) if latencies else 0,
            "by_mode": dict(Counter(t.get("params", {}).get("mode", "unknown") for t in traces)),
            "by_model": dict(Counter(t.get("model", "unknown") for t in traces)),
            "checks": {
                "pass": check_summary.get("pass", 0),
                "review": check_summary.get("review", 0),
                "fail": check_summary.get("fail", 0),
            },
            "top_sources": [
                {"source": source, "citations": count}
                for source, count in sources.most_common(10)
            ],
            "by_day": [
                {"day": day, "count": count} for day, count in sorted(by_day.items())
            ],
        }

    # ---------------------------------------------------------------- replay

    def replay(self, trace_id: str, rag_service) -> dict:
        """
        Re-run a recorded trace and show the result beside the original.

        Two replays are run, because they prove different things:

          retrieval  - re-run retrieval with the trace's recorded params and
                       compare the chunk_ids and scores that come back
          generation - rebuild the model call from the chunks stored IN the
                       trace (not from a fresh search) and compare the output

        If generation matches while retrieval does not, the index moved. If
        retrieval matches while generation does not, the model or prompt moved.
        """

        trace = self.get(trace_id)
        params = trace["params"]

        fresh = rag_service.search(
            trace["question"],
            top_k=params["top_k"],
            min_score=params["min_score"],
            source=params.get("source_filter"),
            mode=params["mode"],
        )

        original = [
            {"chunk_id": hit["chunk_id"], "score": hit["score"]}
            for hit in trace["retrieved"]
        ]
        replayed = [
            {"chunk_id": hit["chunk_id"], "score": round(float(hit["score"]), 4)}
            for hit in fresh["hits"]
        ]

        report = {
            "trace_id": trace_id,
            "retrieval": {
                "original": original,
                "replayed": replayed,
                "identical": original == replayed,
                "same_chunks": [h["chunk_id"] for h in original] == [h["chunk_id"] for h in replayed],
            },
            "generation": None,
        }

        if not trace["passes_gate"]:
            report["generation"] = {
                "skipped": True,
                "reason": "The trace was refused by the gate before any model call.",
            }
            return report

        hits = [
            {
                "chunk_id": hit["chunk_id"],
                "source": hit["source"],
                "heading": hit["heading"],
                "page": hit["page"],
                "text": hit["text"],
            }
            for hit in trace["retrieved"]
        ]

        regenerated = rag_service.llm.generate_answer(trace["question"], hits)

        original_output = (trace.get("raw_output") or "").strip()
        replayed_output = (regenerated["raw_output"] or "").strip()

        report["generation"] = {
            "skipped": False,
            "original": original_output,
            "replayed": replayed_output,
            "identical": original_output == replayed_output,
            "diff": list(
                difflib.unified_diff(
                    original_output.splitlines(),
                    replayed_output.splitlines(),
                    fromfile="original",
                    tofile="replayed",
                    lineterm="",
                )
            ),
            "prompt_version_then": trace.get("prompt_version"),
            "prompt_version_now": regenerated["prompt_version"],
        }

        return report

    # --------------------------------------------------------------- helpers

    @staticmethod
    def with_checks(trace: dict) -> dict:

        checks = run_checks(trace)

        return {**trace, "checks": checks, "check_status": summarise_checks(checks)}


def summarise_trace(trace: dict) -> dict:

    checks = run_checks(trace)

    return {
        "trace_id": trace["trace_id"],
        "timestamp": trace.get("timestamp"),
        "origin": trace.get("origin"),
        "question": trace.get("question"),
        "mode": trace.get("params", {}).get("mode"),
        "model": trace.get("model"),
        "refused": trace.get("refused", False),
        "refused_by": trace.get("refused_by"),
        "latency_ms": trace.get("latency_ms", 0),
        "retrieved_count": len(trace.get("retrieved", [])),
        "cited_count": len(trace.get("cited_chunk_ids", [])),
        "invalid_citations": len(trace.get("invalid_citations", [])),
        "check_status": summarise_checks(checks),
    }


def _percentile(sorted_values: list[int], percent: int) -> int:

    if not sorted_values:
        return 0

    index = round((percent / 100) * (len(sorted_values) - 1))

    return int(sorted_values[index])
