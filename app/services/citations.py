"""
Parsing and verifying the [S#] citation tags the model emits.

Kept in one module because three callers need the same definition of what a
citation looks like: the answer parser in llm_service, the deterministic
quality checks, and the Week 6 evaluation assertions. When they disagreed,
the app under-reported its own citations - see docs/training/week6/results.md.

CITATION_PARSER_VERSION is recorded in every evaluation run, so a before/after
comparison names the parser that produced each number.
"""

import re

CITATION_PARSER_VERSION = "v2"

# v1 (ASCII-only, ~2026-09-04) undercounted citations: the Week 6 baseline
# measured openai/gpt-oss-20b reliably emitting full-width CJK-style brackets
# - "The deductible is $250【S1】【S4】." - for a real, meaningful share of
# answers (3 of 15 M3 cases in the 2026-09-07 baseline run alone). v1 recorded
# those as uncited, dropping a real citation from `sources` and from every
# citation-quality check, in production, not just in a historical trace.
# v2 resolves both bracket shapes into the same verified source number.
CITATION_TAG = re.compile(r"[\[【]\s*S(\d+)\s*[\]】]")

# Superset of shapes has_citation() recognises as "the model attempted a
# citation here" even if a future shape shows up that CITATION_TAG does not
# yet parse - keeps that diagnostic distinction meaningful going forward.
ANY_CITATION_SHAPE = CITATION_TAG


def parse_citations(text: str, source_count: int) -> tuple[list[int], list[str]]:
    """
    Split the tags in `text` into those that name a source that was actually
    provided and those that do not.

    Returns (cited, invalid): `cited` holds 1-based source numbers in the
    order they first appear; `invalid` holds the literal tags that pointed
    outside the range.
    """

    cited: list[int] = []
    invalid: list[str] = []

    for match in CITATION_TAG.finditer(text or ""):

        number = int(match.group(1))

        if 1 <= number <= source_count:
            if number not in cited:
                cited.append(number)
        else:
            invalid.append(match.group(0))

    return cited, invalid


def has_citation(text: str) -> bool:
    """
    True when the text carries at least one citation tag of any shape
    CITATION_TAG resolves. Kept as a separate name (rather than inlining the
    regex at call sites) so a future unresolved shape can be added here first
    - as a diagnostic - before parse_citations() is trusted to act on it.
    """

    return bool(ANY_CITATION_SHAPE.search(text or ""))
