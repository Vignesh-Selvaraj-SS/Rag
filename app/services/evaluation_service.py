"""
Retrieval evaluation against a golden set of questions with known-correct
chunk ids: hit-rate@3, hit-rate@k, MRR and p50 latency, per mode.

Runs against the LIVE index through the production retrieval path
(RetrievalService.retrieve), never a re-implementation, so the numbers
describe what the application actually does. Consolidated from the Week 4
harness (eval_retrieval.py, inspect_failures.py).
"""

import json
import logging
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from app.core.errors import BadRequestError, NotFoundError

logger = logging.getLogger(__name__)

# Retrieved breadth for measurement, independent of the app's TOP_K: wide
# enough to report where an expected chunk landed even when it missed.
EVAL_TOP_K = 10

REQUIRED_FIELDS = ("id", "question", "expected_chunk_id")


class EvaluationService:

    def __init__(self, golden_set_path: Path, runs_dir: Path):

        self.golden_set_path = golden_set_path
        self.runs_dir = runs_dir

    # ------------------------------------------------------------ golden set

    def load_golden_set(self) -> list[dict]:

        if not self.golden_set_path.exists():
            return []

        items = []

        with self.golden_set_path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    items.append(json.loads(line))

        return items

    def save_golden_set(self, items: list[dict]) -> list[dict]:

        cleaned = []
        seen = set()

        for position, item in enumerate(items, start=1):

            for field in REQUIRED_FIELDS:
                if not str(item.get(field) or "").strip():
                    raise BadRequestError(f"Question {position}: '{field}' is required.")

            if item["id"] in seen:
                raise BadRequestError(f"Duplicate question id '{item['id']}'.")

            seen.add(item["id"])

            cleaned.append(
                {
                    "id": item["id"].strip(),
                    "question": item["question"].strip(),
                    "expected_chunk_id": item["expected_chunk_id"].strip(),
                    "expected_heading": (item.get("expected_heading") or "").strip() or None,
                    "exact_token": (item.get("exact_token") or "").strip() or None,
                }
            )

        self.golden_set_path.parent.mkdir(parents=True, exist_ok=True)

        with self.golden_set_path.open("w", encoding="utf-8") as handle:
            for item in cleaned:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")

        return cleaned

    # ------------------------------------------------------------------- run

    def run(
        self,
        retriever,
        mode: str,
        index_metadata: dict | None,
        top_k: int = EVAL_TOP_K,
        label: str | None = None,
    ) -> dict:

        golden_set = self.load_golden_set()

        if not golden_set:
            raise BadRequestError("The golden set is empty. Add at least one question first.")

        per_question = []
        latencies = []

        for item in golden_set:

            started = time.perf_counter()
            retrieval = retriever.retrieve(item["question"], top_k=top_k, mode=mode)
            elapsed_ms = (time.perf_counter() - started) * 1000
            latencies.append(elapsed_ms)

            hits = retrieval["hits"]
            position = _rank_of(item["expected_chunk_id"], hits)

            per_question.append(
                {
                    "id": item["id"],
                    "question": item["question"],
                    "expected_chunk_id": item["expected_chunk_id"],
                    "expected_heading": item.get("expected_heading"),
                    "exact_token": item.get("exact_token"),
                    "rank_of_expected": position,
                    "hit_at_3": position is not None and position <= 3,
                    "hit_at_5": position is not None and position <= 5,
                    "latency_ms": round(elapsed_ms, 1),
                    "top_hits": [
                        {
                            "rank": rank,
                            "chunk_id": hit["chunk_id"],
                            "source": hit["source"],
                            "heading": hit["heading"],
                            "score": round(float(hit["score"]), 4),
                            "dense_score": round(float(hit["dense_score"]), 4),
                            "expected": hit["chunk_id"] == item["expected_chunk_id"],
                        }
                        for rank, hit in enumerate(hits[:5], start=1)
                    ],
                }
            )

        count = len(per_question)
        hits_at_3 = sum(1 for q in per_question if q["hit_at_3"])
        hits_at_5 = sum(1 for q in per_question if q["hit_at_5"])
        reciprocal_ranks = [
            1.0 / q["rank_of_expected"] if q["rank_of_expected"] else 0.0
            for q in per_question
        ]

        warnings = []

        strategy = (index_metadata or {}).get("strategy")

        if strategy and strategy != "heading":
            warnings.append(
                f"The index was built with the '{strategy}' strategy. Golden-set chunk ids "
                "refer to heading-based chunks, so most questions will report a miss."
            )

        if index_metadata is None:
            warnings.append(
                "No index metadata was found; the index may have been built by an older "
                "version. Rebuild it to record strategy and document counts."
            )

        run = {
            "run_id": "run_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "label": (label or "").strip() or None,
            "mode": mode,
            "top_k": top_k,
            "index": {
                "strategy": strategy,
                "chunks": (index_metadata or {}).get("chunks"),
                "built_at": (index_metadata or {}).get("built_at"),
            },
            "n_questions": count,
            "hit_rate_at_3": round(hits_at_3 / count, 4),
            "hit_rate_at_5": round(hits_at_5 / count, 4),
            "hits_at_3": hits_at_3,
            "hits_at_5": hits_at_5,
            "mrr": round(sum(reciprocal_ranks) / count, 4),
            "p50_latency_ms": round(statistics.median(latencies), 1),
            "warnings": warnings,
            "per_question": per_question,
        }

        self._save_run(run)

        logger.info(
            "Evaluation %s: mode=%s hit@3=%.3f (%d/%d) p50=%.1fms",
            run["run_id"], mode, run["hit_rate_at_3"], hits_at_3, count, run["p50_latency_ms"],
        )

        return run

    def inspect(self, rag_service, question_id: str, mode: str) -> dict:
        """
        The inspection view: for one golden-set question, show exactly what
        was fetched (the chunks actually shown to the model) and the final
        generated answer side by side, so a failure can be labelled
        retrieval / generation / not-in-corpus with real evidence.
        """

        items = {item["id"]: item for item in self.load_golden_set()}

        if question_id not in items:
            raise NotFoundError(f"No golden-set question with id '{question_id}'.")

        item = items[question_id]
        expected_chunk_id = item["expected_chunk_id"]

        started = time.perf_counter()
        result = rag_service.ask(item["question"], mode=mode)
        latency_ms = int((time.perf_counter() - started) * 1000)

        retrieved = [
            {
                "rank": rank,
                "chunk_id": hit["chunk_id"],
                "source": hit["source"],
                "heading": hit["heading"],
                "page": hit["page"],
                "score": round(float(hit["score"]), 4),
                "dense_score": round(float(hit["dense_score"]), 4),
                "text": hit["text"],
                "expected": hit["chunk_id"] == expected_chunk_id,
            }
            for rank, hit in enumerate(result["retrieved"], start=1)
        ]

        return {
            "question_id": question_id,
            "question": item["question"],
            "expected_chunk_id": expected_chunk_id,
            "expected_heading": item.get("expected_heading"),
            "mode": mode,
            "expected_was_shown": any(hit["expected"] for hit in retrieved),
            "retrieved": retrieved,
            "answer": result["answer"],
            "refused": result["refused"],
            "refused_by": result["refused_by"],
            "cited_chunk_ids": [hit["chunk_id"] for hit in result["sources"]],
            "invalid_citations": result["invalid_citations"],
            "latency_ms": latency_ms,
        }

    # ------------------------------------------------------------------ runs

    def list_runs(self) -> list[dict]:

        runs = []

        if not self.runs_dir.exists():
            return runs

        for path in sorted(self.runs_dir.glob("run_*.json"), reverse=True):
            try:
                run = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

            runs.append({key: value for key, value in run.items() if key != "per_question"})

        return runs

    def get_run(self, run_id: str) -> dict:

        path = self.runs_dir / f"{run_id}.json"

        if not path.is_file() or not run_id.startswith("run_"):
            raise NotFoundError(f"No evaluation run with id '{run_id}'.")

        return json.loads(path.read_text(encoding="utf-8"))

    def delete_run(self, run_id: str) -> None:

        path = self.runs_dir / f"{run_id}.json"

        if not path.is_file() or not run_id.startswith("run_"):
            raise NotFoundError(f"No evaluation run with id '{run_id}'.")

        path.unlink()

    def _save_run(self, run: dict) -> None:

        self.runs_dir.mkdir(parents=True, exist_ok=True)
        (self.runs_dir / f"{run['run_id']}.json").write_text(
            json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8"
        )


def _rank_of(expected_chunk_id: str, hits: list[dict]) -> int | None:

    for position, hit in enumerate(hits, start=1):
        if hit["chunk_id"] == expected_chunk_id:
            return position

    return None
