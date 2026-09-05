# Phase 1 Audit — Insurance Claims RAG POC

Audit date: 2026-09-04. Branch: `PROD` (identical to `week-5`, `master`, `origin/master`).
No files were modified during this phase.

---

## 1. Current architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  app/static/index.html   (vanilla HTML + JS, served at GET /ui)      │
└───────────────┬─────────────────────────────────────────────────────┘
                │ fetch /api/v1/chat, /api/v1/ingest, /api/v1/documents
┌───────────────▼─────────────────────────────────────────────────────┐
│  FastAPI  app/main.py                                                │
│   api/chat.py  api/ingest.py  api/upload.py                          │
│   services/  rag_service ─► retrieval_service ─► vector_store(Qdrant)│
│                          └► llm_service (Groq)     embedding(fastembed)│
│              chunk_service · document_loader · pdf_ocr               │
│              hybrid_search(BM25+RRF) · reranker · mmr · query_transform│
└─────────────────────────────────────────────────────────────────────┘
   CLI: ingest.py, ask.py          Task folders: week4/, week5/, week6/
```

**There is no Angular application in the POC.** The brief assumes one exists.
The only UI is a 470-line single-file page (`app/static/index.html`) with
inline CSS and JS. Angular CLI 22.0.0 and Node 24 are installed on the
machine, so the production frontend is built new in `frontend/` and consumes
the existing FastAPI backend. Every behaviour of the static page is carried
over (see matrix §9).

### 1.1 Angular structure (requested inventory)

| Item | Finding |
|---|---|
| Angular version | none present; CLI 22.0.0 available → new app targets Angular 22 |
| Components / services / routing / guards / interceptors | none |
| Models / forms / state management | none (plain DOM manipulation in index.html) |
| UI library | none; hand-written CSS with light/dark tokens |
| Assets / styles / configuration | none; API URL is relative (same origin) |

### 1.2 Backend (Python 3.14, FastAPI 0.141)

| Layer | Files | Notes |
|---|---|---|
| App | `app/main.py` | CORS `*`, 3 routers, `/`, `/health`, `/ui` |
| Config | `app/core/config.py` | pydantic-settings; 7 required env vars |
| API | `api/chat.py`, `api/ingest.py`, `api/upload.py` | `POST /api/v1/chat/`, `POST /api/v1/ingest`, `POST /api/v1/documents` |
| Schemas | `schemas/*Schemas.py` | thin request/response models |
| Services | 13 modules in `app/services/` | well-commented, small, single-purpose |

---

## 2. RAG functionality inventory

| Capability | Where | Status |
|---|---|---|
| Document upload (pdf/md/markdown/txt, 20 MB cap, path-traversal safe) | `api/upload.py` | working |
| Document parsing: text + tables (pdfplumber), image OCR + full-page OCR fallback (EasyOCR) | `document_loader.py`, `pdf_ocr.py` | working |
| Chunking: heading-based (markdown / SECTION / numbered), fallback to fixed-size when no headings | `chunk_service.py` | working |
| Chunking: fixed-size 300 words / 50 overlap | `chunk_service.py` | working, switchable |
| Embeddings: fastembed `BAAI/bge-small-en-v1.5`, asymmetric prefixes | `embedding_service.py` | working |
| Vector DB: embedded Qdrant, HNSW tuned, deterministic uuid5 ids, wipe-and-rebuild | `vector_store.py` | working |
| Dense retrieval + metadata filter by `source` | `vector_store.search` | working |
| Hybrid retrieval: BM25 + Reciprocal Rank Fusion (k=60) | `hybrid_search.py` | working (Week 4 outcome) |
| Cross-encoder reranking `BAAI/bge-reranker-base` over 25 candidates | `reranker.py` | working |
| MMR diversity selection (λ=0.5) | `mmr.py` | working |
| Query rewriting (LLM) | `query_transform.py` | working |
| HyDE (hypothetical passage) | `query_transform.py` | working |
| Refusal gate on cosine `dense_score ≥ MIN_SCORE` | `retrieval_service.py` | working |
| Grounded prompt, `[S#]` citation verification, invalid-citation detection, model refusal detection | `llm_service.py` | working |
| Sources = only cited chunks (not all retrieved) | `rag_service.ask` | working |
| Resolved run parameters + prompt version + raw output returned | `rag_service.ask` | working (Week 5 additions) |
| Retrieval-only search (`--search-only`) | `ask.py` | CLI only |
| Per-request `top_k`, `min_score`, `source` filter | `rag_service.ask` | CLI only, not exposed via API |
| Conversation history | `index.html` | client-side display only; no memory sent to model |
| Retrieval evaluation: golden set, hit-rate@3, p50 latency, per-question rank | `week4/eval_retrieval.py`, `golden_set.jsonl` | script, isolated eval index |
| Failure inspection view (question / fetched / answer) | `week4/inspect_failures.py` | script |
| Trace logging with PII redaction (claimant / claim no / policy no) | `week5/trace_logger.py` | library used by scripts, not by API |
| Trace corpus generation from question pool | `week5/run_traces.py` | script |
| Replay a trace: retrieval diff + regeneration diff | `week5/replay.py` | script |
| Seeded random sample of traces | `week5/sample.py` | script |
| Pretty-print traces | `week5/format_traces.py` | script |
| Deterministic answer assertions A5–A8 (no wrong refusal, complete output, citation present, no invalid citations) | `week6/__pycache__/assertions.pyc` | **source deleted; only bytecode remains** |
| Claim summary from adjuster notes + assertions A1–A4 + judge modes M1–M6 | `week6/__pycache__/*.pyc` | **source deleted; only bytecode remains** |
| Agent / tool calling / multi-step workflows | — | not present |
| Multiple knowledge bases | — | not present (one collection) |
| Authentication | — | not present |

---

## 3. Supporting functionality

| Area | Finding |
|---|---|
| Logging | none (print statements in CLIs only) |
| Configuration | env via pydantic-settings; HNSW / RRF / MMR / reranker constants hard-coded with rationale; fixed generation temperature 0.0 and 800 tokens |
| Authentication | none |
| Error handling | `HTTPException` for empty index (503) and bad upload (400); missing Groq key raises `RuntimeError` → unhandled 500; Groq API errors unhandled |
| Testing | **no tests at all** (frontend or backend) |
| Monitoring | none; traces exist only as a week-5 script output |
| Dev tools | `ask.py --search-only`, `inspect_failures.py`, `replay.py` |

---

## 4. Task-specific, duplicate and unused material

| Path | Classification | Decision |
|---|---|---|
| `week4/results.md` | training write-up | move to `docs/training/week4/` |
| `week4/baseline_results.json`, `after_results.json` | measurement evidence | move to `docs/training/week4/` |
| `week4/golden_set.jsonl` | **application data** (evaluation dataset) | move to `evaluation/golden_set.jsonl`, served + editable via API |
| `week4/eval_retrieval.py` | evaluation harness | logic → `app/services/evaluation_service.py`; CLI → `scripts/evaluate.py` |
| `week4/inspect_failures.py` | failure inspection | becomes Developer → Retrieval Inspector + per-question detail in Evaluation UI |
| `week4/.qdrant_eval/` | derived index (git-ignored) | delete |
| `week5/trace_logger.py` | **production-grade** redaction + trace builder | move to `app/services/trace_service.py`, wire into `/chat` |
| `week5/run_traces.py`, `sample.py`, `format_traces.py`, `replay.py` | scripts | replay + sample → `TraceService` + API; run/format → obsolete once API records every chat |
| `week5/traces.jsonl` (100 traces) | evidence corpus | move to `docs/training/week5/` (historical, generated with a different model) |
| `week5/traces.json` (520 KB) | derived pretty-print of the above | delete |
| `week5/notes.md`, `taxonomy.md`, `question_pool.md`, `*-evidence.txt`, `week5-task-D.xlsx` | training material | move to `docs/training/week5/` |
| `week6/__pycache__/*.pyc` | bytecode of deleted sources | delete; A5–A8 checks re-implemented from their docstrings as `trace_checks.py`; claim-summary feature not recoverable |
| `app/static/index.html` | POC UI | replaced by Angular; every behaviour preserved |
| `ingest.py`, `ask.py` (root) | CLIs documented in README | move to `scripts/` |
| `data/.~lock.*.pdf#` | LibreOffice temp lock | delete |
| `app/main.py` `/ui`, `/` welcome | POC endpoints | `/ui` removed; `/` serves the Angular build when present |
| `week4/hybrid_retrieval.py` referenced in `hybrid_search.py` comment | already deleted | fix stale comment |

Duplicates: `README.md` "Layout" and endpoint tables are stale (list only two endpoints, describe a "no reranker / dense only" system that has since gained five retrieval modes). `results.md` §8 contains a historical copy of the hybrid logic; production copy lives in `hybrid_search.py`. No live duplicate implementations exist in `app/`.

---

## 5. Production gaps

1. No frontend framework, no component structure, no tests.
2. `/chat` hides everything the POC computes: retrieved chunks, scores, params, refusal reason, invalid citations, latency, prompt version.
3. Traces (with redaction) exist but are never written by the API.
4. No document list / delete; no index status (count, strategy, last build).
5. Evaluation only runnable from a script against a separate index.
6. No structured logging, request ids, or consistent error shape; missing API key surfaces as a raw 500.
7. CORS wide open; no configurable origins.
8. `.env` is required to contain all seven variables or the app fails to start.
9. Long-running operations (ingest with OCR, reranker model download) block the event loop (`async def` calling sync code).

---

## 6. Recommended final architecture

```
Rag/
├── app/                       FastAPI backend (kept, extended)
│   ├── api/   chat, search, documents, index, evaluation, traces, settings, health
│   ├── core/  config (defaults, CORS, paths, logging), errors, request-id middleware
│   ├── schemas/
│   └── services/  rag, retrieval, vector_store, embedding, llm, chunk, loader, ocr,
│                  hybrid_search, reranker, mmr, query_transform,
│                  index_metadata, trace_service, trace_checks, evaluation_service
├── evaluation/golden_set.jsonl
├── scripts/ingest.py, ask.py, evaluate.py
├── tests/                     pytest API tests (service layer faked)
├── frontend/                  Angular 22 app
│   └── src/app/ core/ shared/ layout/ features/{chat,documents,evaluation,analytics,settings,developer}
├── docs/AUDIT.md, MIGRATION_REPORT.md, training/week4, training/week5
└── data/                      the knowledge base documents
```

Product feature map (only what exists or follows directly from the POC):

| Area | Backed by |
|---|---|
| Chat | `/chat` (extended), citations, retry/regenerate, copy, markdown, sample questions |
| Documents (incl. Knowledge Base overview) | upload, list, delete, rebuild index with strategy, index status |
| Evaluation | golden set CRUD, run hit-rate@3 / p50 evaluation, run history, per-question ranks |
| Analytics | aggregate of recorded traces (answered / refused, refusal source, latency, modes, top sources) |
| Settings | retrieval defaults (mode, top-k, min score, source filter), developer mode, server configuration |
| Developer | Retrieval Inspector (search-only), Trace browser + detail, Replay, Quality checks |

Not built (no POC basis): multiple knowledge bases, agents/tools, authentication, claim-summary judge (source lost).

---

## 7. Feature Preservation Matrix

| Feature | Current Location | Keep | Refactor | Remove | Target Location |
|---|---|---|---|---|---|
| Ask question with cited sources | `api/chat.py`, `index.html` | ✔ | ✔ | | `features/chat`, `POST /api/v1/chat` |
| Search mode selector (dense/hybrid/rerank/mmr/rewrite/hyde) | `index.html` select | ✔ | ✔ | | Settings → Retrieval defaults; per-chat override in Developer mode |
| Sample questions | `index.html` | ✔ | | | Chat empty state |
| Conversation feed, clear chat, typing indicator | `index.html` | ✔ | ✔ | | `features/chat` (signals store, retry/regenerate/copy added) |
| Rebuild index with chunking strategy | `index.html`, `api/ingest.py` | ✔ | ✔ | | Documents page, `POST /api/v1/index/rebuild` (old path kept) |
| Upload document | `api/upload.py`, `index.html` | ✔ | ✔ | | Documents page, `POST /api/v1/documents` |
| List / delete documents | — | | | | new: `GET/DELETE /api/v1/documents` (natural completion of upload) |
| Index status (chunks, strategy, built at) | — (chunk_count only) | | | | new: `index_metadata.py`, `GET /api/v1/index` |
| Per-request top_k / min_score / source | `ask.py` CLI | ✔ | ✔ | | `ChatRequest` fields; Settings → Advanced |
| Search-only retrieval | `ask.py --search-only` | ✔ | ✔ | | `POST /api/v1/search`; Developer → Retrieval Inspector |
| Retrieved chunks / scores / gate / refusal reason / invalid citations / params / prompt version | `rag_service.ask` (dropped by API) | ✔ | ✔ | | `ChatResponse.debug`, Developer mode panel in chat |
| Hybrid BM25+RRF | `hybrid_search.py` | ✔ | | | unchanged |
| Reranker, MMR, rewrite, HyDE | services | ✔ | | | unchanged |
| PDF text/table/OCR loading | `document_loader.py`, `pdf_ocr.py` | ✔ | | | unchanged |
| Heading + fixed-size chunking | `chunk_service.py` | ✔ | | | unchanged |
| Redacting trace logger | `week5/trace_logger.py` | ✔ | ✔ | | `services/trace_service.py`, recorded on every `/chat` |
| Trace replay (retrieval + generation diff) | `week5/replay.py` | ✔ | ✔ | | `POST /api/v1/traces/{id}/replay`; Developer → Traces |
| Seeded trace sample | `week5/sample.py` | ✔ | ✔ | | `GET /api/v1/traces/sample?seed=&n=` |
| Trace corpus runner | `week5/run_traces.py` | | | ✔ | superseded: API records traces; question pool kept in docs |
| Pretty-print traces | `week5/format_traces.py` | | | ✔ | superseded by trace detail API/UI |
| Golden set + hit-rate@3 + p50 latency | `week4/eval_retrieval.py`, `golden_set.jsonl` | ✔ | ✔ | | `services/evaluation_service.py`, `evaluation/golden_set.jsonl`, Evaluation page |
| Failure inspection (question / fetched / answer) | `week4/inspect_failures.py` | ✔ | ✔ | | Evaluation per-question detail + Developer inspector |
| Answer quality checks A5–A8 | `week6/*.pyc` (source lost) | ✔ | ✔ | | `services/trace_checks.py`; shown on traces and analytics |
| Claim-summary judge, A1–A4, modes M1–M6 | `week6/*.pyc` (source lost) | | | ✔ | not recoverable; documented |
| Week 4/5 write-ups, evidence, xlsx | `week4/`, `week5/` | ✔ | | | `docs/training/` |
| `traces.json` (derived) | `week5/` | | | ✔ | delete |
| `.qdrant_eval`, `__pycache__`, lock file | various | | | ✔ | delete |
| CLIs `ingest.py`, `ask.py` | root | ✔ | ✔ | | `scripts/` |
| `/ui` static page | `app/main.py`, `app/static` | | | ✔ | replaced by Angular app |
| CORS `*` | `app/main.py` | | ✔ | | `CORS_ORIGINS` setting |
