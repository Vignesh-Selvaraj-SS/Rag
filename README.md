# Insurance Claims RAG Assistant

A production-structured Retrieval-Augmented Generation application for an
insurance endorsement pack: a FastAPI backend that answers **only** from the
documents in `data/`, cites the file and page for every fact, refuses when the
documents do not cover the question, and an Angular 22 frontend that makes all
of it usable without knowing what RAG is.

```
┌──────────────── Angular 22 (frontend/) ─────────────────┐
│ Chat · Documents · Evaluation · Analytics · Settings     │
│ Developer: retrieval inspector · traces · replay        │
└───────────────────────────┬─────────────────────────────┘
                            │ /api/v1
┌───────────────────────────▼─────────────────────────────┐
│ FastAPI (app/)                                          │
│  chat/search · documents/index · evaluation · traces    │
│  RAGService → RetrievalService → Qdrant (embedded)      │
│             → LLMService (Groq)   fastembed bge-small   │
│  hybrid BM25+RRF · cross-encoder rerank · MMR · HyDE    │
│  redacting trace log · golden-set evaluation            │
└─────────────────────────────────────────────────────────┘
```

---

## Quick start

**Backend** (Python 3.12+; tested on 3.14)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

copy .env.example .env        # add your GROQ_API_KEY (console.groq.com/keys)

.\.venv\Scripts\python.exe scripts\ingest.py          # build the index from data/
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

**Frontend**

```bash
cd frontend
npm install
npm start                      # http://localhost:4200 (API on :8000)
```

For a single-origin deployment run `npm run build`; FastAPI then serves the
built app at `http://127.0.0.1:8000/` automatically (see `FRONTEND_DIST`).

Interactive API docs: `http://127.0.0.1:8000/docs`.

> **Embedded Qdrant lock.** Qdrant runs inside the API process and locks
> `.qdrant/` to one process at a time. Stop the server before running the CLI
> scripts, or point `QDRANT_PATH`/a Qdrant server at a shared instance.

Only answer generation needs the Groq key. Without it the app starts, indexes
and retrieves; Chat reports that generation is not configured (HTTP 503).

---

## Application areas

| Area | What you can do | Backed by |
|---|---|---|
| **Chat** | Ask questions, see cited sources with file + page, click a citation to highlight its source, copy, regenerate, retry, clear. Sample questions on the empty state. | `POST /api/v1/chat` |
| **Documents** | Knowledge-base overview (documents, chunks, strategy, last build), upload (drag-and-drop, type/size validation), delete, rebuild the index with heading-based or fixed-size chunking, per-document status. | `GET/POST/DELETE /api/v1/documents`, `GET /api/v1/index`, `POST /api/v1/index/rebuild` |
| **Evaluation** | Edit the golden set, run hit-rate@3 / hit-rate@5 / MRR / p50 latency per retrieval mode against the live index, keep a run history with before/after deltas, inspect any question (what was retrieved vs. what was answered). | `/api/v1/evaluation/*` |
| **Analytics** | Answered vs. refused, refusal source (gate vs. model), latency percentiles, automatic quality checks, most-cited documents, questions per day, recent questions. | `GET /api/v1/traces/stats` |
| **Settings** | Search mode (dense, hybrid, rerank, MMR, rewrite, HyDE), Advanced RAG configuration (top-k, similarity gate, document filter), Developer mode, theme, read-only server configuration. | `GET /api/v1/settings` |
| **Developer** (opt-in) | Retrieval inspector (search without generating, compare all modes), trace browser with filters and seeded sampling, trace detail with checks and raw output, replay (retrieval + generation diff). Chat answers also show retrieved chunks, scores, gate decision and parameters. | `POST /api/v1/search`, `/api/v1/traces/*` |

Every question asked through the API is recorded as a trace with claimant
names, claim numbers and policy numbers **redacted before the record is
written** (`app/services/trace_service.py`).

---

## Layout

```
app/
  main.py                  app factory, CORS, request ids, error handlers, SPA mount
  core/    config.py       all settings (pydantic-settings, defaults for everything but the key)
           errors.py       AppError hierarchy → {"detail", "request_id"} JSON
           logging.py, request_id.py
  api/     chat.py         POST /chat, POST /search
           documents.py    documents, index status, rebuild (+ legacy /ingest)
           evaluation.py   golden set, runs, inspect
           traces.py       list, stats, sample, detail, replay
           settings.py     GET /settings, GET /health
  schemas/                 pydantic request/response models per area
  services/
    document_loader.py   1  files in, text out, page numbers kept (PDF text, tables, OCR)
    chunk_service.py     2  heading-based (fallback fixed-size) and fixed-size chunking
    embedding_service.py 3  fastembed bge-small, asymmetric prefixes
    vector_store.py      4  embedded Qdrant, HNSW, wipe-and-rebuild
    retrieval_service.py 5  dense · hybrid · rerank · mmr · rewrite · hyde, similarity gate
    hybrid_search.py        BM25 + reciprocal rank fusion
    reranker.py, mmr.py, query_transform.py
    llm_service.py       6  grounded prompt, citation verification, refusal detection
    rag_service.py          orchestration + index rebuild
    index_metadata.py       what the index was built from (strategy, counts, time)
    document_service.py     files on disk joined with index status
    trace_service.py        redaction, append-only JSONL, stats, sampling, replay
    trace_checks.py         deterministic quality checks per trace
    evaluation_service.py   golden-set retrieval evaluation + inspection
    catalog.py              the modes and strategies the UI offers
    shared.py               lazily built singletons (Qdrant allows one client)
evaluation/golden_set.jsonl  the evaluation dataset (editable in the UI)
scripts/   ingest.py · ask.py · evaluate.py
tests/     pytest API + service tests (fakes for Qdrant/embeddings/LLM)
frontend/  Angular 22 app (see frontend/README.md)
docs/      AUDIT.md (POC audit), MIGRATION_REPORT.md, training/ (course write-ups)
data/      the knowledge base documents
```

Runtime data lives outside the source tree: `.qdrant/` (index + metadata) and
`.runtime/` (traces, evaluation runs). Both are git-ignored.

---

## Configuration

All settings are environment variables (or `.env`); see `.env.example`.

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | *(none)* | enables answer generation, query rewriting and HyDE |
| `MODEL_NAME` | `llama-3.3-70b-versatile` | Groq chat model |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | fastembed model (prefixes in `embedding_service.py`) |
| `QDRANT_PATH` / `COLLECTION_NAME` | `.qdrant` / `insurance_claims` | embedded vector store |
| `TOP_K` / `MIN_SCORE` | `5` / `0.60` | default chunks shown to the model / similarity gate |
| `DATA_DIR`, `EVALUATION_DIR`, `RUNTIME_DIR` | `data`, `evaluation`, `.runtime` | storage folders |
| `RECORD_TRACES` | `true` | record a redacted trace per question |
| `MAX_UPLOAD_MB` | `20` | upload limit |
| `CORS_ORIGINS` | `http://localhost:4200,http://127.0.0.1:4200` | allowed browser origins |
| `FRONTEND_DIST` | `frontend/dist/rag-assistant/browser` | serve the built UI from `/` when present |
| `LOG_LEVEL` | `INFO` | |

Generation temperature (0.0), max tokens (800), HNSW, RRF and MMR constants are
deliberately fixed in code with their rationale; the UI shows them read-only.

---

## Testing

```powershell
.\.venv\Scripts\python.exe -m pytest          # backend: 50 tests, no network, no models
cd frontend; npm test                          # frontend: vitest unit tests
cd frontend; npm run build                     # production build + budgets
```

---

## The RAG design, briefly

- **Chunking** follows document structure (markdown, `SECTION 4`, `4.1 Loss
  Settlement` headings), falling back to 300-word windows for documents with no
  detectable headings. The file and heading are prepended before embedding so a
  chunk like "a separate deductible of $500 applies" knows what it is for.
- **Retrieval** is dense by default (measured: recall stops improving after 5
  chunks). Hybrid BM25 + RRF is available for exact identifiers such as
  `HO-2026-08`; cross-encoder reranking, MMR, query rewriting and HyDE are
  selectable per user.
- **Refusal** happens twice: a cheap cosine gate (0.60) stops off-domain
  questions before any model call, and the prompt instructs the model to answer
  only from the numbered sources. Citation tags are verified against what was
  actually provided; invented tags are flagged, never trusted.
- **Sources** returned to the UI are only the chunks the answer cited, not
  everything retrieved. Developer mode shows the rest.

The measurements behind these choices are in `docs/training/`.
