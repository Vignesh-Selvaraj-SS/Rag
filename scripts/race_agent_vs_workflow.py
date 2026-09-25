"""
Race ClaimAgent (hand-built agent loop) against FixedClaimWorkflow (hardcoded
two-step sequence) on the same claim scenarios, and print real numbers:
speed, cost (tokens), and reliability (did the answer actually cover every
fact the claim asked for).

    python scripts/race_agent_vs_workflow.py

Stop the API server first: embedded Qdrant locks its folder to one process.
Needs GROQ_API_KEY.
"""

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.core.errors import AppError  # noqa: E402
from app.services.agent_service import ClaimAgent  # noqa: E402
from app.services.fixed_claim_workflow import FixedClaimWorkflow  # noqa: E402
from app.services.retrieval_service import RetrievalService  # noqa: E402

SCENARIOS_PATH = REPO_ROOT / "evaluation" / "agent_race_scenarios.json"
RESULTS_PATH = REPO_ROOT / ".runtime" / "agent_race" / "results.json"


def score_reliability(answer: str, expected_keywords: list[str]) -> tuple[int, int]:
    """
    How many of the facts the claim actually asked for show up in the
    answer, case-insensitive substring match. Deterministic and free,
    same reasoning as the Week 6 assertions: this is not a judgement call,
    so no model call is spent checking it.
    """

    answer_lower = (answer or "").lower()
    found = sum(1 for kw in expected_keywords if kw.lower() in answer_lower)

    return found, len(expected_keywords)


def _run_system(run_fn, claim: str, expected_keywords: list[str]) -> dict:
    """
    Runs one system on one scenario, isolating a hard upstream failure (e.g.
    Groq's daily token cap, live-observed hitting mid-race) to this one
    system/scenario cell instead of losing the whole race. Mirrors
    scripts/race_triage.py's _run_system, added after this exact script
    crashed on a real live run rather than reporting a partial result.
    """

    try:
        result = run_fn(claim)
    except AppError as error:
        return {
            "answer": None, "sources": [], "steps": [], "step_count": 0,
            "tokens_used": 0, "latency_ms": 0, "stopped_reason": "error",
            "finished": False, "keywords_found": 0,
            "keywords_total": len(expected_keywords), "error": str(error),
        }

    found, total = score_reliability(result["answer"] or "", expected_keywords)

    return {
        "answer": result["answer"],
        "sources": result["sources"],
        "steps": result["steps"],
        "step_count": result["step_count"],
        "tokens_used": result["tokens_used"],
        "latency_ms": result["latency_ms"],
        "stopped_reason": result.get("stopped_reason", "finished"),
        "finished": result["finished"],
        "keywords_found": found,
        "keywords_total": total,
    }


def run_scenario(scenario: dict, agent: ClaimAgent, workflow: FixedClaimWorkflow) -> dict:

    claim = scenario["claim"]
    expected_keywords = scenario["expected_keywords"]

    return {
        "id": scenario["id"],
        "complexity": scenario["complexity"],
        "claim": claim,
        "expected_keywords": expected_keywords,
        "agent": _run_system(agent.run, claim, expected_keywords),
        "workflow": _run_system(workflow.run, claim, expected_keywords),
    }


def main() -> int:

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="+", default=None, help="restrict to these scenario ids")
    parser.add_argument("--sleep", type=float, default=0.0, help="seconds to pause between scenarios, to stay under the Groq tokens-per-minute limit")
    args = parser.parse_args()

    scenarios = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))

    if args.only:
        wanted = set(args.only)
        scenarios = [s for s in scenarios if s["id"] in wanted]

    retriever = RetrievalService()

    if retriever.vector_store.count() == 0:
        print("The index is empty. Run: python scripts/ingest.py")
        return 1

    agent = ClaimAgent(retriever=retriever)
    workflow = FixedClaimWorkflow(retriever=retriever)

    results = []

    for i, scenario in enumerate(scenarios):
        if i > 0 and args.sleep:
            print(f"(sleeping {args.sleep}s to stay under the rate limit)")
            time.sleep(args.sleep)
        print(f"[{scenario['id']}] ({scenario['complexity']}) racing ...", end="", flush=True)
        started = time.perf_counter()
        result = run_scenario(scenario, agent, workflow)
        results.append(result)
        print(f" done ({time.perf_counter() - started:.1f}s)")

        # Saved after every scenario, not just at the end - a hard upstream
        # failure (Groq's daily token cap, live-observed mid-race) no longer
        # loses every scenario run before it.
        RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    if not results:
        print("No scenarios completed.")
        return 1

    print()
    header = f"{'id':<5}{'complexity':<11}{'agent steps':>12}{'agent tok':>11}{'agent ms':>10}{'agent rel':>11}{'fixed tok':>11}{'fixed ms':>10}{'fixed rel':>11}"
    print(header)
    print("-" * len(header))

    for r in results:
        a, w = r["agent"], r["workflow"]
        a_rel = f"{a['keywords_found']}/{a['keywords_total']}"
        w_rel = f"{w['keywords_found']}/{w['keywords_total']}"
        print(
            f"{r['id']:<5}{r['complexity']:<11}{a['step_count']:>12}{a['tokens_used']:>11}"
            f"{a['latency_ms']:>10}{a_rel:>11}{w['tokens_used']:>11}{w['latency_ms']:>10}{w_rel:>11}"
        )

    total_agent_tokens = sum(r["agent"]["tokens_used"] for r in results)
    total_workflow_tokens = sum(r["workflow"]["tokens_used"] for r in results)
    total_agent_ms = sum(r["agent"]["latency_ms"] for r in results)
    total_workflow_ms = sum(r["workflow"]["latency_ms"] for r in results)
    agent_rel = sum(r["agent"]["keywords_found"] for r in results)
    workflow_rel = sum(r["workflow"]["keywords_found"] for r in results)
    total_keywords = sum(r["agent"]["keywords_total"] for r in results)

    print()
    print(f"totals: agent {total_agent_tokens} tok, {total_agent_ms}ms, {agent_rel}/{total_keywords} facts covered")
    print(f"        fixed {total_workflow_tokens} tok, {total_workflow_ms}ms, {workflow_rel}/{total_keywords} facts covered")

    print(f"\nSaved: {RESULTS_PATH.relative_to(REPO_ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
