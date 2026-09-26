"""
Normalizes an agent's step log and a fixed workflow's step log into one
shared shape for the API to return, so any UI can render both traces the
same way.

The two shapes differ because the fixed workflows predate this API: an
agent's steps already look like `{tool, args, result, thought, tokens}`
(one entry per real tool call); a fixed workflow's steps look like
`{action, result|raw|result_count, tokens}` (one entry per hardcoded stage,
described in prose, not a tool call). Used by both app/api/triage.py and
app/api/policy_qa.py - extracted here once it was about to be copied a
second time for the second agent/workflow pair.
"""

_WORKFLOW_STEP_META_KEYS = {"step", "action", "latency_ms", "tokens"}


def _normalize_workflow_step(step: dict) -> dict:

    action = step.get("action", "")

    if "get_claim" in action:
        tool = "get_claim"
    elif "search_policy" in action:
        tool = "search_policy"
    elif "compute_payout" in action:
        tool = "compute_payout"
    elif "generate" in action:
        tool = "generate_decision"  # the workflow's one free-text generation call - not a tool call at all
    else:
        tool = action.split(" ")[0] if action else "unknown"

    extra = {key: value for key, value in step.items() if key not in _WORKFLOW_STEP_META_KEYS}

    return {
        "step": step["step"],
        "tool": tool,
        "thought": action,
        "args": None,
        "result": extra or None,
        "latency_ms": step.get("latency_ms", 0),
        "tokens": step.get("tokens"),
    }


def normalize_steps(steps: list[dict]) -> list[dict]:
    """An agent's steps already match the shared shape; a fixed workflow's don't - see _normalize_workflow_step."""

    return [step if "tool" in step else _normalize_workflow_step(step) for step in steps]
