# Week 4 — Debugging Retrieval — Task Set D (Insurance Claims)

Domain corpus: `data/` (12 real documents: base HO-3 policy, 8 endorsements, 2 claims
procedures, 1 policyholder FAQ). Index: heading-based chunking (the app's default),
`BAAI/bge-small-en-v1.5`, 107 chunks. All numbers below were measured, not estimated —
see `week4/eval_retrieval.py`, `week4/hybrid_retrieval.py`, `week4/inspect_failures.py`,
`week4/golden_set.jsonl`, `week4/baseline_results.json`, `week4/after_results.json`.

---

## 1. Golden set (12 real adjuster questions, known-correct `chunk_id`)

Every question below is answerable from a single, specific section of the real corpus.
9 of 12 (well above the required 4) hinge on an exact token — an endorsement number
(`HO-2026-0X`) or a procedural reason code (`DUP-01`) — the category this project's own
README already flags as dense retrieval's weak spot ("Known limits" section).

| id | question | expected_chunk_id | exact token |
|---|---|---|---|
| Q1 | What is the deductible for a water backup claim under endorsement HO-2026-01, and does it stack with the base all-perils deductible? | `endorsement-HO-2026-01-water-backup.md::4` | HO-2026-01 |
| Q2 | Under endorsement HO-2026-02, exactly where does service line coverage begin and end? | `endorsement-HO-2026-02-service-line.md::2` | HO-2026-02 |
| Q3 | Under endorsement HO-2026-03, what settlement basis applies to covered equipment that is 10 years or older? | `endorsement-HO-2026-03-equipment-breakdown.md::7` | HO-2026-03 |
| Q4 | Which territories currently prohibit roof ACV settlement under endorsement HO-2026-08? | `endorsement-HO-2026-08-roof-surfaces-acv.md::6` | HO-2026-08 |
| Q5 | Under endorsement HO-2026-05, what is the time limit for actually completing repairs before increased ordinance-or-law costs stop being payable? | `endorsement-HO-2026-05-ordinance-or-law.md::5` | HO-2026-05 |
| Q6 | How many client visits per week are allowed for a home business to still qualify under endorsement HO-2026-06? | `endorsement-HO-2026-06-home-business.md::2` | HO-2026-06 |
| Q7 | Under endorsement HO-2026-07, is a ransomware payment reimbursed automatically, or are there conditions attached? | `endorsement-HO-2026-07-identity-fraud.md::5` | HO-2026-07 |
| Q8 | Under endorsement HO-2026-04, how long does a policyholder have to claim back withheld depreciation after actually repairing or replacing the property? | `endorsement-HO-2026-04-scheduled-property.md::1` | HO-2026-04 |
| Q9 | What is the reserve authority limit for a Senior field adjuster? | `claims-adjuster-authority.md::1` | — |
| Q10 | How soon must a claim number be issued after First Notice of Loss, regardless of the channel it comes through? | `claims-fnol-procedure.md::1` | — |
| Q11 | What emergency mitigation spend can an intake handler authorise without adjuster approval? | `claims-fnol-procedure.md::4` | — |
| Q12 | What reason code should be used when closing a duplicate claim number that was issued in error? | `claims-fnol-procedure.md::6` | DUP-01 |

Full machine-readable set: [`golden_set.jsonl`](golden_set.jsonl).

---

## 2. Baseline hit-rate@3 (measured before any change)

```
mode=dense  hit_rate@3=0.917 (11/12)  p50_latency=13.3ms
```

11 of 12 hit. **One miss: Q2.** Full detail in [`baseline_results.json`](baseline_results.json).

---

## 3. Failure tally (R / G / Not-in-Corpus)

Only one question missed hit-rate@3, so the tally has one entry — that entry was run
through the inspection view (`inspect_failures.py`), which shows the exact TOP_K=5 chunks
the LLM actually received and the final generated answer, side by side.

| Label | Count |
|---|---|
| **R** — retrieval fetched bad context | **1** (Q2) |
| G — model misused good context | 0 |
| Not-in-Corpus | 0 |

**Q2 — labelled R.** Evidence from the inspection view:

> Expected chunk `endorsement-HO-2026-02-service-line.md::2` ("Definition of service
> line" — the section stating coverage "begins at the point the line leaves the
> exterior wall of the dwelling and ends at the utility company's connection point **or
> the boundary of the residence premises, whichever comes first**") was **not among the
> 5 chunks shown to the LLM** (`expected chunk shown to LLM: False`). In its place, the
> model was shown three *other* chunks from the same file — the title/metadata chunk,
> the exclusions chunk, and the "What this endorsement does" overview — plus two
> unrelated endorsements' title chunks. Deprived of the real definition, the model
> answered from the overview chunk instead: *"coverage... begins at the dwelling and
> ends at the utility connection point"* — plausible-sounding, but it silently drops the
> "or the boundary of the residence premises, whichever comes first" qualifier that the
> real definition carries. This is exactly the failure mode in the task's problem
> statement: fluent, semantically-adjacent context, not the precise clause. Confirmed R,
> not G, precisely *because* the correct chunk was absent from what the model saw — per
> the task's own common-mistake warning, this was checked directly rather than inferred
> from the answer being imprecise.

No G or Not-in-Corpus cases occurred in this run — worth stating plainly rather than
manufacturing one. 11 of 12 real questions were answered by dense retrieval alone.

---

## 4. The one retrieval change: BM25 + RRF fusion (k=60)

**Chosen over cross-encoder reranking, justified by two pieces of evidence:**

1. **The tally.** The one real failure (Q2) is precisely the category this project's own
   README already documents as dense retrieval's structural weak spot: *"Dense retrieval
   only. Exact identifiers like `HO-2026-08` or 'territory 41' are where embeddings are
   weakest and keyword search is strongest. Hybrid BM25 + dense would fix it."* — written
   before this week's work, based on the same corpus.
2. **This exact codebase already tried reranking and rejected it.** README's "Known
   limits" section: *"No reranker. A cross-encoder over the top 20 improved rank-1
   accuracy but hurt whether the right chunk showed up in the top 5 at all, so it was
   left out."* Re-running the same experiment this week would spend the week's one
   change re-discovering a result that's already on record. (I also confirmed Q2's
   correct chunk sits at dense rank 13/107 — inside a top-25 rerank window — so reranking
   was structurally *able* to fix this one case too; it just isn't the one with a clean
   track record here.)

**Implementation** ([`hybrid_retrieval.py`](hybrid_retrieval.py), new file — the full diff
is in §8): dense search over the whole collection and BM25 (`rank_bm25`, same tokenizer,
hyphens/dots kept inside tokens so `HO-2026-02` and `DUP-01` survive as single tokens) are
each ranked independently, then fused by **Reciprocal Rank Fusion**: `score = Σ 1/(60 +
rank)` per list a chunk appears in. RRF fuses *ranks*, not raw scores — BM25 scores and
cosine similarity live on unrelated scales and were never meant to be added or averaged,
a mistake the task sheet explicitly calls out.

Kept isolated in `week4/` rather than wired into `app/services/retrieval_service.py` for
*this evaluation* — this is one retrieval change, fully isolated and independently
diffable, not a modification to a system already serving traffic, so the measurement
below can't be accused of testing something other than what it claims to test. (It was
later wired into the live app as a separate, explicit decision — see the postscript in
§7 — but that came after and independent of this measurement.)

---

## 5. After: hit-rate@3 and p50 latency

```
mode=dense   hit_rate@3=0.917 (11/12)  p50_latency=13.3ms   <- before
mode=hybrid  hit_rate@3=0.917 (11/12)  p50_latency=15.0ms   <- after
```

| | Before (dense) | After (hybrid) | Δ |
|---|---|---|---|
| hit-rate@3 | 0.917 (11/12) | 0.917 (11/12) | **+0.000** |
| p50 latency | 13.3 ms | 15.0 ms | +1.7 ms (+13%) |

Full detail: [`after_results.json`](after_results.json).

---

## 6. Per-question fixed / unfixed / still-broken

| id | before rank | after rank | before hit@3 | after hit@3 | status |
|---|---|---|---|---|---|
| Q1 | 1 | 1 | ✓ | ✓ | unchanged (already hit) |
| **Q2** | **None (13/107 full ranking)** | **4** | ✗ | ✗ | **improved, not fixed** |
| Q3 | 1 | 1 | ✓ | ✓ | unchanged |
| Q4 | 1 | 1 | ✓ | ✓ | unchanged |
| Q5 | 1 | 1 | ✓ | ✓ | unchanged |
| Q6 | 1 | 1 | ✓ | ✓ | unchanged |
| Q7 | 1 | 1 | ✓ | ✓ | unchanged |
| Q8 | 2 | 2 | ✓ | ✓ | unchanged |
| Q9 | 1 | 1 | ✓ | ✓ | unchanged |
| Q10 | 1 | 1 | ✓ | ✓ | unchanged |
| Q11 | 1 | 1 | ✓ | ✓ | unchanged |
| Q12 | 1 | 1 | ✓ | ✓ | unchanged |

**Which R-failure the change fixed:** none, by the hit-rate@3 bar. **Which it did not
touch at all:** the other 11 questions were untouched in both directions — no
regressions, but no wins beyond Q2 either.

**The honest nuance on Q2**, named precisely because it matters for the shipping call:
the correct chunk moved from completely absent out of the top 10 (rank 13 of 107 in the
full dense ordering) to **rank 4** under hybrid. Rank 4 is outside the hit-rate@3 window
this task measures, but it is *inside* the app's real production `TOP_K=5` — meaning in
the actual running app (not just this metric), Q2 would very likely now be answered
correctly, even though the specific number this task asks for did not move.

---

## 7. Shipping decision

**By the letter of the metric this task specifies (hit-rate@3 on these 12 questions):
do not ship on this evidence.** hit-rate@3 is unchanged, 0.917 → 0.917, and latency rose
~13% (13.3ms → 15.0ms) for zero movement in the headline number. If hit-rate@3 is the bar,
the honest read is "not worth it" — exactly the outcome the task explicitly permits
reporting.

**But the number that actually moved (Q2's rank: unranked → 4th) says something the
metric doesn't capture**, and it's worth being explicit about rather than hiding behind
the flat headline: it moved the one real failure from "wrong content entirely" to
"correct content, ranked one place below where the app actually cuts off." That's a
genuine, if partial, win that a stricter hit-rate@5 would have shown as a clean fix.

**Recommendation:** don't ship *this specific fusion* on the strength of the required
metric alone — 12 questions and one partial win is too thin a result to justify a
permanent retrieval-path change and a latency cost. But don't discard hybrid retrieval
either: the one failure it didn't fully fix moved in exactly the right direction, for
free (no regressions on the other 11), at a cost (2.8ms) that's genuinely trivial next to
the seconds an LLM call already costs. The right next step is more data, not a verdict —
grow the golden set past 12 questions (particularly more exact-token cases, since that's
the category this fix targets) before deciding whether the real hit-rate@3 delta is
"basically zero" or "we didn't have enough failing questions to see it yet."

**Postscript, for anyone reading this after the fact**: the recommendation above was made
on this week's evidence alone, and stands as this week's answer — hit-rate@3 on 12
questions did not justify shipping hybrid by itself. Separately, after this evaluation was
complete, hybrid retrieval *was* wired into the live app as an explicit user request,
independent of this measurement (`app/services/hybrid_search.py`, exposed as an opt-in
`mode` toggle — dense search remains the default everywhere). That later decision doesn't
retroactively change the number above; it's a different decision made with different
information (the user wanted the capability available regardless of what a 12-question
sample showed). Recorded here so this document stays accurate rather than implying the
app was never touched.

---

## 8. Code diff — the one retrieval change

**Update, after this evaluation closed**: `week4/hybrid_retrieval.py` (shown below as
originally submitted) has since been **removed**. Once hybrid retrieval was separately
wired into the live app as `app/services/hybrid_search.py` (see the §7 postscript), having
two independent copies of the same BM25+RRF logic — one graded, one running in
production — meant they could silently drift apart over time. `week4/eval_retrieval.py`
now calls the production methods directly (`VectorStore.search()` /
`VectorStore.search_hybrid()`), and was re-run to confirm this changed nothing about the
result: **hit-rate@3 still 0.917 → 0.917, Q2 still moves from unranked to rank 4** (latency
numbers throughout this document reflect that re-run, and shifted slightly — 13.3ms →
15.0ms rather than the original 11.1ms → 13.9ms — which is ordinary run-to-run timing
variance, not a change in what's being measured). The diff below is kept as the historical
record of what was actually written and evaluated for this task; the logic it shows now
lives at `app/services/hybrid_search.py` instead of at the path shown here.

`requirements.txt` (new dependency for BM25):

```diff
diff --git a/requirements.txt b/requirements.txt
index d973894..14f238c 100644
--- a/requirements.txt
+++ b/requirements.txt
@@ -8,3 +8,4 @@ qdrant-client>=1.15,<2
 fastembed>=0.8,<1
 groq>=1.6,<2
 pypdf>=6,<7
+rank-bm25>=0.2,<1
```

`week4/hybrid_retrieval.py` (new file — the retrieval change itself; `DenseOnlyRetriever`
is an unmodified wrapper around the existing production path, included only so the
evaluation harness can call "before" and "after" through the same interface):

```diff
diff --git a/week4/hybrid_retrieval.py b/week4/hybrid_retrieval.py
new file mode 100644
index 0000000..a7b952e
--- /dev/null
+++ b/week4/hybrid_retrieval.py
@@ -0,0 +1,129 @@
+"""
+Two retriever wrappers used by the Week 4 evaluation harness.
+
+DenseOnlyRetriever mirrors the app's current production retrieval path
+exactly (app/services/retrieval_service.py) - this is the "before".
+
+HybridRetriever is the ONE retrieval change made this week: BM25
+keyword search fused with the same dense results via Reciprocal Rank
+Fusion (RRF, k=60) - this is the "after". It is additive and isolated
+here rather than wired into app/services/, so the production app is
+untouched pending the shipping decision in results.md.
+"""
+
+import re
+
+from rank_bm25 import BM25Okapi
+
+from app.core.config import DATA_DIR
+from app.services.chunk_service import create_chunks_for_all, embed_text
+from app.services.document_loader import load_directory
+
+RRF_K = 60
+
+
+def _tokenize(text: str) -> list[str]:
+    # Keep hyphens and dots inside tokens so "HO-2026-01" and "CP-09"
+    # survive as single tokens rather than being split into fragments.
+    return re.findall(r"[a-z0-9][a-z0-9\-\.]*", text.lower())
+
+
+class DenseOnlyRetriever:
+    """The current production retrieval path, unchanged - the baseline."""
+
+    def __init__(self, vector_store, embedding_service):
+        self.vector_store = vector_store
+        self.embedding_service = embedding_service
+
+    def retrieve(self, question: str, top_k: int) -> list[dict]:
+
+        query_embedding = self.embedding_service.generate_query_embedding(question)
+
+        results = self.vector_store.search(query_embedding=query_embedding, top_k=top_k)
+
+        return [
+            {
+                "chunk_id": r["chunk_id"],
+                "score": r["score"],
+                "source": r["source"],
+                "heading": r["heading"],
+            }
+            for r in results
+        ]
+
+
+class HybridRetriever:
+    """
+    Dense (embedding) search fused with BM25 (keyword) search via
+    Reciprocal Rank Fusion. RRF fuses RANKS, not raw scores - BM25 and
+    cosine similarity are not on the same scale and were never meant
+    to be added or averaged together.
+    """
+
+    def __init__(self, vector_store, embedding_service):
+
+        self.vector_store = vector_store
+        self.embedding_service = embedding_service
+
+        documents = load_directory(DATA_DIR)
+        self.chunks = create_chunks_for_all(documents)
+        self.chunk_by_id = {chunk["chunk_id"]: chunk for chunk in self.chunks}
+        self.chunk_ids_in_order = [chunk["chunk_id"] for chunk in self.chunks]
+
+        corpus = [_tokenize(embed_text(chunk)) for chunk in self.chunks]
+        self.bm25 = BM25Okapi(corpus)
+
+    def retrieve(self, question: str, top_k: int) -> list[dict]:
+
+        # Dense ranking over the WHOLE collection, so RRF has a full
+        # rank position for every chunk dense search "knows about" -
+        # not just the app's usual top_k window.
+        query_embedding = self.embedding_service.generate_query_embedding(question)
+        dense_results = self.vector_store.search(
+            query_embedding=query_embedding,
+            top_k=len(self.chunks),
+        )
+        dense_rank = {r["chunk_id"]: position for position, r in enumerate(dense_results, start=1)}
+
+        # BM25 ranking over the same corpus, same tokenizer used for
+        # both sides so an exact token like "HO-2026-08" or "DUP-01"
+        # matches identically in the query and in the indexed text.
+        bm25_scores = self.bm25.get_scores(_tokenize(question))
+        bm25_ranked = sorted(
+            zip(self.chunk_ids_in_order, bm25_scores),
+            key=lambda pair: pair[1],
+            reverse=True,
+        )
+        bm25_rank = {chunk_id: position for position, (chunk_id, _) in enumerate(bm25_ranked, start=1)}
+
+        # Reciprocal Rank Fusion, k=60: 1/(k+rank) per list, summed.
+        # A chunk missing from one list simply doesn't get that term -
+        # it isn't penalised beyond not being there.
+        fused_scores = {}
+        for chunk_id in set(dense_rank) | set(bm25_rank):
+
+            score = 0.0
+
+            if chunk_id in dense_rank:
+                score += 1.0 / (RRF_K + dense_rank[chunk_id])
+
+            if chunk_id in bm25_rank:
+                score += 1.0 / (RRF_K + bm25_rank[chunk_id])
+
+            fused_scores[chunk_id] = score
+
+        fused_ranked = sorted(fused_scores.items(), key=lambda pair: pair[1], reverse=True)
+
+        hits = []
+        for chunk_id, score in fused_ranked[:top_k]:
+            chunk = self.chunk_by_id[chunk_id]
+            hits.append(
+                {
+                    "chunk_id": chunk_id,
+                    "score": score,
+                    "source": chunk["source"],
+                    "heading": chunk["heading"],
+                }
+            )
+
+        return hits
```

Supporting harness (not part of the "one change" itself — tooling to measure it):
[`eval_retrieval.py`](eval_retrieval.py) (hit-rate@3 + p50 latency, before/after),
[`inspect_failures.py`](inspect_failures.py) (the inspection view: question / fetched /
final answer side by side, used to produce the §3 evidence).

---

## 9. Bonus challenge (MMR) — not attempted

The bonus scenario (top-3 for one query all being the *same* exclusion text repeated
across different form editions) doesn't have a real analogue in this corpus — this
corpus has no repeated-edition documents, so MMR has nothing genuine to diversify against
here. Rather than construct an artificial version of that scenario to claim the bonus, I
left it out: the task sheet's own common mistakes list warns against writing test cases
to make a result look a particular way, and manufacturing a near-duplicate-editions
scenario that doesn't exist in the real data would be exactly that, just for the bonus
section instead of the golden set.
