"""Unit tests for pure service logic: chunking, fusion, redaction, checks."""

from app.services.chunk_service import (
    create_chunks,
    create_fixed_size_chunks,
    embed_text,
    page_label,
)
from app.services.hybrid_search import BM25Index, fuse_with_rrf
from app.services.trace_checks import run_checks, summarise_checks
from app.services.trace_service import collect_identifiers, redact, scrub


# ------------------------------------------------------------------ chunking

def _document(text: str, pages: list[str] | None = None) -> dict:
    pages = pages or [text]
    return {
        "source": "doc.md",
        "title": "Doc",
        "pages": [{"page": number, "text": page} for number, page in enumerate(pages, start=1)],
        "text": "\n".join(pages),
        "word_count": len(text.split()),
    }


def test_heading_chunking_splits_on_all_three_heading_families():

    text = (
        "Preamble line.\n"
        "## Coverage\nCovered things.\n"
        "SECTION 4 - Exclusions\nNot covered.\n"
        "4.1 Loss Settlement\nSettled at ACV.\n"
        "1. a list item, not a heading\n"
    )

    chunks = create_chunks(_document(text))

    assert [chunk["heading"] for chunk in chunks] == ["Overview", "Coverage", "SECTION 4 - Exclusions", "4.1 Loss Settlement"]
    assert chunks[0]["chunk_id"] == "doc.md::0"
    assert "1. a list item" in chunks[-1]["text"]


def test_heading_chunking_falls_back_to_fixed_size_without_structure():

    text = " ".join(f"word{number}" for number in range(700))

    chunks = create_chunks(_document(text))

    assert len(chunks) == 3
    assert chunks[0]["heading"] == "words 1-300"
    assert chunks[1]["heading"] == "words 251-550"


def test_fixed_size_chunks_track_page_spans():

    page_one = " ".join(["one"] * 200)
    page_two = " ".join(["two"] * 200)

    chunks = create_fixed_size_chunks(_document(page_one + "\n" + page_two, [page_one, page_two]))

    assert (chunks[0]["page_start"], chunks[0]["page_end"]) == (1, 2)
    assert chunks[-1]["page_end"] == 2
    assert page_label(1, 2) == "pp.1-2"
    assert page_label(3, 3) == "p.3"


def test_embed_text_prepends_source_and_heading():

    chunk = {"source": "a.md", "heading": "Deductible", "text": "A $500 deductible applies."}

    assert embed_text(chunk) == "a.md > Deductible\n\nA $500 deductible applies."


# --------------------------------------------------------------------- hybrid

def test_rrf_fusion_keeps_dense_score_separate_from_fused_score():

    chunks = [
        {"chunk_id": "a", "source": "a.md", "heading": "HO-2026-02 definition", "text": "service line HO-2026-02"},
        {"chunk_id": "b", "source": "b.md", "heading": "Roof", "text": "roof surfaces acv"},
        {"chunk_id": "c", "source": "c.md", "heading": "Water", "text": "water backup"},
    ]

    index = BM25Index(chunks)
    bm25_rank = index.rank("HO-2026-02")

    assert min(bm25_rank, key=bm25_rank.get) == "a"

    dense = [
        {"chunk_id": "b", "score": 0.9},
        {"chunk_id": "c", "score": 0.8},
        {"chunk_id": "a", "score": 0.7},
    ]

    fused = fuse_with_rrf(dense, bm25_rank, index.chunk_by_id, top_k=2)

    assert fused[0]["chunk_id"] in {"a", "b"}
    assert all(0 < hit["score"] < 0.05 for hit in fused)
    assert {hit["chunk_id"]: hit["dense_score"] for hit in fused}["b"] == 0.9


# ------------------------------------------------------------------ redaction

def test_redaction_is_trigger_based_not_shape_based():

    assert redact("claimant Maria Delgado reported CLM-482911 on policy HO-5591027") == (
        "claimant [CLAIMANT] reported [CLAIM_NO] on policy [POLICY_NO]"
    )
    # A heading-shaped title-case pair is NOT a name without a trigger.
    assert redact("Water Backup and Sump Discharge") == "Water Backup and Sump Discharge"
    # Form codes never match the policy-number pattern.
    assert redact("endorsement HO-2026-01") == "endorsement HO-2026-01"


def test_scrub_removes_identifiers_echoed_in_new_shapes():

    question = "What is the deductible for claimant Maria Delgado's water backup claim?"
    identifiers = collect_identifiers(question)

    answer = "The deductible for Maria Delgado's water-backup claim is $500. Delgado must pay it."

    assert scrub(answer, identifiers) == (
        "The deductible for [CLAIMANT]'s water-backup claim is $500. [CLAIMANT] must pay it."
    )


# --------------------------------------------------------------------- checks

def _trace(**overrides) -> dict:
    base = {
        "refused": False,
        "refused_by": None,
        "answer": "The deductible is $500 [S1].",
        "cited_chunk_ids": ["a.md::1"],
        "invalid_citations": [],
        "retrieved": [{"dense_score": 0.8}],
    }
    return {**base, **overrides}


def test_checks_pass_for_a_clean_answer():

    results = run_checks(_trace())

    assert {r["id"]: r["status"] for r in results} == {
        "refusal": "pass",
        "output_complete": "pass",
        "citation_present": "pass",
        "no_invalid_citations": "pass",
    }
    assert summarise_checks(results) == "pass"


def test_checks_flag_truncation_missing_citation_and_invented_tags():

    results = run_checks(
        _trace(answer="The deductible is $500 and the", cited_chunk_ids=[], invalid_citations=["[S7]"])
    )
    statuses = {r["id"]: r["status"] for r in results}

    assert statuses["output_complete"] == "fail"
    assert statuses["citation_present"] == "fail"
    assert statuses["no_invalid_citations"] == "fail"
    assert summarise_checks(results) == "fail"


def test_model_refusal_is_flagged_for_review_and_gate_refusal_is_skipped():

    model = run_checks(_trace(refused=True, refused_by="model", cited_chunk_ids=[]))
    assert {r["id"]: r["status"] for r in model}["refusal"] == "review"
    assert summarise_checks(model) == "review"

    gate = run_checks(_trace(refused=True, refused_by="gate", cited_chunk_ids=[], retrieved=[]))
    assert {r["id"]: r["status"] for r in gate}["refusal"] == "skip"
    assert summarise_checks(gate) == "pass"
