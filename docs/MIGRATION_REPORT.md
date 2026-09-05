# Migration Report — POC → Production RAG Application

Date: 2026-09-04 · Branch: `PROD` · **Nothing has been committed**; all changes are in the working tree.
Companion document: [AUDIT.md](AUDIT.md) (Phase 1 findings and the Feature Preservation Matrix).

---

## A. Existing POC features

Discovered in the audit (details and locations in AUDIT.md §2):

1. Grounded Q&A over `data/` with `[S#]` citations, citation verification and refusal detection (`/chat`).
2. Similarity gate (`MIN_SCORE`) that refuses off-domain questions before a model call.
3. Six retrieval modes: dense, hybrid (BM25 + RRF), cross-encoder rerank, MMR, query rewrite, HyDE.
4. Per-request `top_k`, `min_score` and `source` filter (CLI only).
5. Retrieval-only search (`ask.py --search-only`).
6. Two chunking strategies (heading-based with fixed-size fallback; fixed-size) selectable at ingest.
7. PDF loading with text, tables, embedded-image OCR and full-page OCR fallback; page-accurate citations.
8. Document upload with type and size validation and path-traversal protection.
9. Index rebuild from the data folder.
10. Static chat UI: conversation feed, sample questions, mode and strategy selectors, upload, rebuild, clear.
11. Week 4: golden set (12 questions), hit-rate@3 / p50 latency harness, failure inspection view.
12. Week 5: redacting trace logger (claimant / claim / policy identifiers), trace corpus runner, seeded sampling, replay (retrieval + generation diff), pretty-printer, write-ups.
13. Week 6: deterministic answer assertions (A5–A8) and a claim-summary judge — **source files deleted, bytecode only**.

## B. Preserved features

Every item in A.1–A.12 is preserved. Items 4 and 5 (previously CLI-only) are now part of the product; items 11 and 12 (previously scripts) are now services with API endpoints and UI screens. The A.13 assertions A5–A8 were re-implemented from their documented criteria as `trace_checks.py`.

## C. Refactored features

| Feature | Change |
|---|---|
| Chat API | `ChatRequest` accepts mode, top_k, min_score, source and `include_debug`; response adds refusal reason, trace id, latency, cited ranks and an optional debug block (retrieved chunks, params, prompt version, raw output, invalid citations). Handler runs in the thread pool (blocking calls). |
| Search | New `POST /api/v1/search` exposes the existing retrieve-only path. |
| Documents | Upload logic moved to `DocumentService`; added list (with derived indexed/pending/removed status) and delete. Index metadata (`index_meta.json`) records strategy, counts and build time. `/ingest` kept as a hidden alias of `/index/rebuild`. |
| Evaluation | `eval_retrieval.py` + `inspect_failures.py` → `EvaluationService`: runs against the live index through the production retriever, adds hit-rate@5 and MRR, persists runs for before/after comparison, golden set editable via API. |
| Traces | `trace_logger.py` + `sample.py` + `replay.py` → `TraceService`: every `/chat` call records a redacted trace; list/filter, stats, seeded sample, detail with quality checks, replay. |
| Configuration | All settings have defaults except the API key; new `CORS_ORIGINS`, `RUNTIME_DIR`, `RECORD_TRACES`, `MAX_UPLOAD_MB`, `FRONTEND_DIST`, `LOG_LEVEL`. |
| Errors | `AppError` hierarchy, one JSON shape `{detail, request_id}`, request-id middleware, friendly messages for missing key (503), upstream model errors (502), empty index (503), validation (422). |
| Services wiring | `shared.py` builds singletons lazily; routers depend on providers (`api/deps.py`) so tests inject fakes. |
| Schemas | camelCase modules replaced by per-area snake_case modules with full response models. |
| CLIs | `ingest.py`, `ask.py` moved to `scripts/` and switched to the lazy providers; `scripts/evaluate.py` added. |
| UI | The single static page is replaced by the Angular application described in F and G. |

## D. Removed features

| Feature | Reason |
|---|---|
| `run_traces.py` (bulk trace generation from a question pool) | Superseded: the API records a trace for every question. The question pool is kept in `docs/training/week5/`. |
| `format_traces.py` | Superseded by the trace detail endpoint and UI. |
| Week 6 claim-summary judge, assertions A1–A4, modes M1–M6 | Source was already deleted from the repository; only `.pyc` files remained. Not reconstructable with confidence. A5–A8 were recovered as `trace_checks.py`. |
| `GET /ui` static page, `GET /` welcome JSON | Replaced by the Angular build served at `/` (JSON description remains when no build exists). |

No RAG capability was removed.

## E. Removed / moved files

Removed: `app/static/index.html`, `app/api/ingest.py`, `app/api/upload.py`, `app/schemas/chatSchemas.py`, `app/schemas/ingestSchemas.py`, `app/schemas/uploadSchemas.py`, `week4/eval_retrieval.py`, `week4/inspect_failures.py`, `week4/.qdrant_eval/`, `week5/trace_logger.py`, `week5/run_traces.py`, `week5/replay.py`, `week5/sample.py`, `week5/format_traces.py`, `week5/__init__.py`, `week5/traces.json` (derived copy), `week6/__pycache__/`, `data/.~lock.*.pdf#`, all `__pycache__/`.

Moved: `week4/{results.md, baseline_results.json, after_results.json}` → `docs/training/week4/`; `week5/{notes.md, taxonomy.md, question_pool.md, replay-evidence.txt, sample-evidence.txt, week5-task-D.xlsx, traces.jsonl}` → `docs/training/week5/`; `week4/golden_set.jsonl` → `evaluation/golden_set.jsonl`; `ingest.py`, `ask.py` → `scripts/`.

## F. Final architecture

```
Rag/
├── app/                        FastAPI backend
│   ├── main.py                 app factory, CORS, request ids, error handlers, SPA mount
│   ├── core/                   config · errors · logging · request_id
│   ├── api/                    deps · chat(+search) · documents(+index) · evaluation · traces · settings(+health)
│   ├── schemas/                common · chat · documents · evaluation · traces · settings
│   └── services/               loader · chunking · embeddings · vector_store · retrieval · hybrid · reranker
│                               mmr · query_transform · llm · rag · index_metadata · document_service
│                               trace_service · trace_checks · evaluation_service · catalog · shared
├── evaluation/golden_set.jsonl
├── scripts/                    ingest.py · ask.py · evaluate.py
├── tests/                      53 pytest tests
├── frontend/                   Angular 22 (standalone, zoneless, signals, vitest)
│   └── src/app/
│       ├── core/               config · models · interceptors · guards · services (API + preferences)
│       ├── shared/             components (empty/error/loading state, chunk card, score bar, badge,
│       │                       confirm dialog, toasts, page header) · pipes · markdown service
│       ├── layout/             main-layout (sidebar shell) · health-indicator
│       ├── features/           chat · documents · evaluation · analytics · settings · developer
│       └── app.routes.ts       lazy routes, developer routes guarded
├── docs/                       AUDIT.md · MIGRATION_REPORT.md · training/
└── data/                       knowledge-base documents
```

Runtime state (`.qdrant/`, `.runtime/`) is outside the source tree and git-ignored.

## G. UI improvements

- **Layout**: sidebar navigation (Chat, Documents, Evaluation, Analytics, Settings, Developer when enabled), responsive drawer on small screens, health indicator (API / index / model key), light and dark themes, skip link and focus styles.
- **Chat**: conversation with user/assistant bubbles, sanitised Markdown rendering, `[S#]` tags rendered as clickable chips that highlight the matching source, source chips with file › heading · page, copy, regenerate, retry-in-place on failure, clear with confirmation, sample questions, typing indicator, per-answer mode and latency, clear refusal explanations (gate vs. model), conversation restored across reloads (session storage).
- **Documents**: knowledge-base overview card (documents, chunks, strategy, last build, up-to-date / pending), drag-and-drop or button upload with progress and client-side validation, per-document status badges, delete with confirmation, rebuild with strategy picker and explanation.
- **Evaluation**: run per mode with optional label, stat tiles (hit@3, hit@5, MRR, p50, misses) with deltas against the previous run, per-question table with expandable top hits, golden-set editor (typed reactive form array), run history, inspect drawer (retrieved vs. answer with the expected chunk marked).
- **Analytics**: stat tiles, quality-check breakdown, mode usage, most-cited documents, questions per day, recent questions.
- **Settings**: search mode with descriptions, Advanced RAG configuration (top-k, gate, document filter) collapsed by default, Developer mode switch, theme, read-only server configuration.
- **States**: every page has loading, empty and error states; errors carry a Retry and, in Developer mode, status / request id / backend detail.

## H. RAG organisation

The pipeline modules are unchanged in behaviour and keep their numbered reading order (loader → chunking → embeddings → vector store → retrieval → LLM). Around them:

- `RAGService` orchestrates ask / search / ingest and now writes index metadata.
- `catalog.py` is the single source of truth for modes and strategies, served by `/settings` so the UI never hard-codes them.
- Retrieval scores are presented honestly: hybrid and rerank show the ranking score and the cosine similarity separately, and the gate line is drawn on the similarity.
- Constants that were deliberately fixed (temperature 0.0, HNSW, RRF k, MMR λ, candidate pool) stay in code with their rationale and are displayed read-only.

## I. Developer mode

Switched on in Settings; hides nothing from the normal user when off.

| Moved from POC | Where it lives now |
|---|---|
| `ask.py --search-only` | Developer → Retrieval inspector (single mode or compare all modes) |
| `inspect_failures.py` | Evaluation → Inspect (per golden question) and the chat "Details" panel |
| Retrieved chunks, scores, gate decision, params, prompt version, raw output (computed but hidden by the old API) | Chat → Details under each answer |
| `trace_logger.py` output | Developer → Traces (filters, pagination) and trace detail |
| `sample.py` | Developer → Traces → seeded random sample |
| `replay.py` | Trace detail → Replay (retrieval and generation comparison with diff) |
| Week 6 assertions A5–A8 | Quality checks on every trace and in Analytics |
| HTTP status, request id, backend detail | Error states everywhere |

## J. Testing

| Suite | Result |
|---|---|
| Backend `pytest` (53 tests): chat, search, documents, index, evaluation, traces, settings, health, serving; unit tests for chunking, RRF fusion, redaction/scrubbing, quality checks; path-traversal tests for delete and run ids | **53 passed** |
| Frontend `ng test` (vitest, 28 tests): preferences store, chat store (ask/retry/regenerate/clear, request body), markdown sanitising and citation chips, error interceptor mapping, pipes, developer guard, documents page states and rebuild, root component | **28 passed** |
| Frontend `ng build` (production, budgets) | **passes** — initial bundle 327 kB raw / 92 kB transfer, all features lazy-loaded |
| Live smoke test (uvicorn on :8011 with the real index) | health, settings, documents, index, dense and hybrid search, validation errors, SPA fallback, JSON 404 for unknown API paths all verified |

Not run: an end-to-end browser test suite (none existed; none added), and answer generation against Groq (needs a live key and spends tokens; the generation path is covered with fakes).

## K. Production readiness

```text
[x] POC cleanup
[x] Task-specific code cleanup
[x] Feature preservation
[x] Angular architecture
[x] User-friendly UI
[x] API services
[x] Error handling
[x] Loading states
[x] Validation
[x] Security          (DOMPurify on model output, safe link handling, filename sanitising,
                       CORS allow-list, no secrets to the client, API-path 404 never serves the SPA)
[x] Performance       (lazy routes, OnPush, cached server config, health polled every 30 s)
[x] Accessibility     (labels, roles, aria-live regions, focus-visible, skip link, reduced motion)
[x] Unit tests
[x] Integration tests (FastAPI TestClient against routers + real service code with faked stores)
[x] RAG evaluation
[x] Documentation     (README, AUDIT, this report, frontend README)
[x] Production build
```

### Known follow-ups

1. **Rebuild the index once.** The existing `.qdrant/` index predates `index_meta.json`, so Documents shows every file as "Needs rebuild" and Evaluation warns about missing metadata until the first rebuild.
2. **Authentication** is not present (none existed). Add it before exposing the API beyond a trusted network; `CORS_ORIGINS` is the only boundary today.
3. **Long operations** (rebuild with OCR, first reranker download) run synchronously in the request thread pool. A background job with progress would improve the Documents page for very large corpora.
4. **Week 6 claim-summary judge** could be rebuilt if the source is recovered from another machine.
5. The golden set's chunk ids assume heading-based chunking; the UI warns when the index uses fixed-size chunks.
