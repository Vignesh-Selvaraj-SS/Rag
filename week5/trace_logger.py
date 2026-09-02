"""
Write one complete, replayable trace per request to a JSONL file.

Claimant identifiers are redacted in `build_trace`, before the record is
serialised - the unredacted string never reaches the file. Redacting the
file afterwards would leave the raw names on disk in between, which is the
exposure this is meant to prevent.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

TRACE_FILE = Path(__file__).resolve().parent / "traces.jsonl"

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


def build_trace(
    trace_id: str,
    question: str,
    result: dict,
    latency_ms: int,
    chunk_strategy: str,
    question_id: str | None = None,
    question_kind: str | None = None,
    origin: str = "random",
) -> dict:
    """
    Assemble one trace. Everything needed to replay the run is stored:
    prompt version, retrieved chunk_ids with scores, model, resolved
    params, and the raw model output before parsing.
    """

    # Taken from the question, because that is the only place the caller
    # supplied them - then scrubbed from every field the model could have
    # echoed them into.
    identifiers = collect_identifiers(question)

    return {
        "trace_id": trace_id,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "question_id": question_id,
        "question_kind": question_kind,
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


def append_trace(trace: dict, path: Path = TRACE_FILE) -> None:

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(trace, ensure_ascii=False) + "\n")


def load_traces(path: Path = TRACE_FILE) -> list[dict]:

    if not path.exists():
        return []

    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]
