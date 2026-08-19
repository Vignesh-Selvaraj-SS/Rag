# Insurance Claims RAG Backend

Week 3 · Module 2 · Retrieval & RAG — Track D

A FastAPI service that answers questions from an insurance endorsement pack. It
answers only from the documents in [data/](data/), reports which file **and page**
each answer came from, and says "I don't know" when the answer isn't there.

---

## The idea in one paragraph

A language model has never seen Meridian Mutual's endorsement pack. Ask it about
the water backup deductible and it will invent a plausible number, in exactly the
confident tone it uses for real facts. RAG fixes that by doing the reading for it:
cut the documents into pieces, turn each into a vector capturing its meaning, and
store those. When a question arrives, turn it into a vector too, find the pieces
pointing in a similar direction, and paste them into the prompt with an
instruction to answer only from them and cite them. **The model stops recalling
and starts reading.**

---

## Layout

```
app/
  main.py                     FastAPI app, CORS, routers
  core/config.py              all settings, validated by pydantic-settings
  api/
    chat.py                   POST /chat
    ingest.py                 POST /ingest
  schemas/                    request and response models
  services/
    document_loader.py    1   files in, text out, page numbers kept
    chunk_service.py      2   cut into pieces, respecting document structure
    embedding_service.py  3   text in, 384 numbers out
    vector_store.py       4   Qdrant + HNSW
    retrieval_service.py  5   find the closest pieces, check they're close enough
    llm_service.py        6   Groq writes the answer, citations verified
    rag_service.py            orchestrates the above
    shared.py                 one shared RAGService instance
```

The numbers are the pipeline order. Read the services in that order and you have
the system.

Command-line tools at the root, using the same services as the API:

| Command | Does |
| --- | --- |
| `python ingest.py` | build the index |
| `python ask.py "..."` | ask a question |

---

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

copy .env.example .env      # then paste your key from console.groq.com/keys

.\.venv\Scripts\python.exe ingest.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Then open **http://127.0.0.1:8000/docs** for the interactive API.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chat/ \
  -H "Content-Type: application/json" \
  -d '{"question":"What deductible applies to a water backup claim?"}'
```

> **The embedded Qdrant lock.** Qdrant runs inside this process by default and
> locks `.qdrant/` to one process at a time. While the API server is running,
> `python ask.py` will fail to open the same index — that is the lock working,
> not a bug. Stop the server first, or run Qdrant as a real server (`docker run
> -p 6333:6333 qdrant/qdrant`) and point `QDRANT_URL` at it if both need to run
> at once.

Only answer generation needs the Groq key. Ingestion and retrieval run locally
with no network calls:

```powershell
python ingest.py                            # no key
python ask.py "..." --search-only           # no key
```

---

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/chat/` | Answer a question, with cited sources |
| `POST` | `/api/v1/ingest` | Rebuild the index from `data/` |

`POST /chat/` returns a deliberately thin shape:

```json
{"answer": "...", "sources": [{"source": "policy-base-HO3-2026.md", "heading": "...", "page": "p.3"}]}
```

`sources` is only what the answer **actually cited** — not everything
retrieved. Returning every retrieved chunk as "sources" regardless of what the
model used is a common shortcut, and it quietly lies: if the model cited
nothing, the caller would still see a confident list of documents that had no
part in the answer.

---

## The concepts

### Embeddings

An embedding turns text into 384 numbers, positioned so texts with similar
*meaning* land near each other. That's what keyword search can't do:

> **Question:** *"How long do I have to send in a signed proof of loss?"*
> **Document:** *"Submit a signed, sworn **proof of loss within 60 days**..."*

A keyword search for "how long" finds nothing. The embeddings match because the
meanings are close.

This is a **bi-encoder**: question and chunk are embedded separately and never
meet, so every chunk vector is computed once at ingest and reused forever. That's
what makes search fast. A **cross-encoder** feeds both through together — more
accurate, far too slow to run over a whole collection. Tested as an optional
reranking step, it raised the top answer's rank but *dropped* the chance of the
right chunk appearing anywhere in the top 5 — a real tradeoff, not a pure win —
so it isn't used here.

The model is `BAAI/bge-small-en-v1.5`, chosen by measurement against four
candidates. **MTEB** is the leaderboard you *shortlist* from, not the one you
*decide* from — it measures average performance on public datasets, not on your
endorsement pack:

| Model | Dims | Download | Found every answer? |
| --- | ---: | ---: | ---: |
| **bge-small-en-v1.5** | 384 | **0.07 GB** | **Yes** |
| bge-base-en-v1.5 | 768 | 0.21 GB | No |
| all-MiniLM-L6-v2 | 384 | 0.09 GB | No — missed 3 of 16 |
| multilingual-e5-large | 1024 | 2.24 GB | Yes |

**`all-MiniLM-L6-v2` — the model most RAG tutorials use — never finds 3 of the 16
answers here.** And `bge-base` scored *worse* than `bge-small` despite being 3×
the size. Bigger is not automatically better. `bge-small` was chosen as the
smallest model that still found everything.

Each family also wants different prefixes (BGE: `"Represent this sentence..."`;
E5: `"query: "` / `"passage: "`; MiniLM: none). Getting it wrong costs accuracy
while everything still *appears* to work, so they live in `PREFIXES` in
[embedding_service.py](app/services/embedding_service.py).

### Chunking

Embedding makes **one vector per piece**. Embed a 1,000-word policy and you get a
blurry average of every topic in it, matching nothing sharply.

`chunk_service.py` splits purely on **document structure** — one chunk per
detected heading, from that heading to the next. Structure here is not just
markdown. Real policy PDFs have no `#` characters; they have `SECTION 4`,
`ARTICLE II`, `4.1 Loss Settlement`. The heading pattern matches all three
families, because a markdown-only splitter degrades silently to one giant
section per document on exactly the files this system exists for.

There is no size budget, no merging of small sections, no splitting of large
ones, and no overlap between chunks — a chunk is exactly what the document's
structure says it is. On the sample corpus that produces roughly 25-95-word
chunks, one per heading.

**The heading goes into the vector.** A chunk reading *"A separate deductible of
$500 applies"* is unanswerable alone — for what? The file and heading are
prepended before embedding; the stored text stays clean.

This is a deliberate tradeoff, not a pure win. A section with no sub-heading of
its own can still come out very large — the same blurry-vector failure a
700-word fixed-size chunk showed when size-based chunking was tested earlier —
and a document with very fine-grained headings produces many small chunks.
There is no `CHUNK_SIZE`/`CHUNK_OVERLAP` knob left to reach for if that shows up
on a real document; the fix would be reintroducing size-based
merging/splitting, scoped to whichever sections turn out to be a problem.

Retrieving more than 5 chunks (`TOP_K`) was also tested up to 20 — recall
stopped improving completely after 5, so anything higher is pure token cost
for zero benefit. That's why `TOP_K=5`.

### Vector database and HNSW

**HNSW** builds a layered graph you enter at a sparse top layer and walk downhill
toward the nearest neighbours — a few hundred comparisons instead of all of them.
Three knobs are set explicitly in [vector_store.py](app/services/vector_store.py)
rather than left as invisible defaults:

| Knob | Meaning | Raising it |
| --- | --- | --- |
| `HNSW_M` | links per node | better recall, more memory, slower build |
| `HNSW_EF_CONSTRUCT` | effort while inserting | better graph, slower ingest, **paid once** |
| `HNSW_EF_SEARCH` | effort per query | better recall, slower queries, **paid every time** |

Qdrant returns cosine **similarity** directly (1.0 = identical), unlike Chroma and
FAISS which return a distance you have to flip. This project was built and tested
on both Chroma and Qdrant at one point; the retrieval numbers came out identical
between them — the vector database is an index, not a ranker, so swapping it
changes operational properties, not accuracy.

**Metadata filtering** narrows the search *before* the vector comparison — pass
`source` to scope a query to one file. In a real claims system that's how you'd
scope to the endorsements attached to *this* policy, restrict to what a user may
see, or filter to the version in force on the date of loss. A similarity score
can't express any of those.

### Grounded answers, and saying "I don't know"

**Search always returns something.** Ask about the 1998 World Cup and it returns
its five least-bad chunks. Pass those on unchecked and you get a fluent,
fictional answer.

The tempting fix is a score threshold. **Measured, it isn't enough**: the worst
genuine question scores 0.662 and the worst out-of-scope question ("How much does
motorcycle insurance cost with Meridian Mutual?") scores 0.696. The ranges
overlap, so no threshold separates them. Every question about insurance *looks*
like insurance — the words "Meridian Mutual", "insurance" and "cost" are all over
the documents, and the embedding has no way to express that *motorcycle* is the
word that matters.

So refusal happens in two places:

1. **The score gate at 0.60** ([retrieval_service.py](app/services/retrieval_service.py)).
   Kills questions from another domain without a model call — the World Cup
   question scores 0.382 and never reaches Groq. Set *below* the value that would
   catch more junk, deliberately: wrongly refusing a policyholder whose answer
   **is** in the documents is worse than paying for one junk API call. **A cost
   optimisation, not the safety mechanism.**
2. **The prompt** ([llm_service.py](app/services/llm_service.py)). The only layer
   that actually *reads*. It also verifies its own citations — if the model cites
   a source tag it was never given, that's flagged rather than trusted silently.

Verified end to end at one point: 16 of 16 answerable questions answered with the
correct source cited, and 5 of 5 out-of-scope questions correctly refused.

---

## Using the real endorsement pack

Delete the sample documents, drop the real files into [data/](data/) — `.pdf`,
`.md` and `.txt` all load — and re-run `python ingest.py` (or `POST /api/v1/ingest`).
PDFs keep their page numbers, so citations become page numbers rather than just a
file name.

`TOP_K=5` and `bge-small` were measured against the sample corpus — re-measure
rather than assuming they still win if answers stop showing up. Chunking is
structure-based with no size setting, so its output depends entirely on how
consistently the real documents use headings; a document with long headerless
stretches will produce a few very large chunks instead of many small ones.

---

## Known limits

- **Dense retrieval only.** Exact identifiers like `HO-2026-08` or "territory 41"
  are where embeddings are weakest and keyword search is strongest. Hybrid
  BM25 + dense would fix it.
- **No reranker.** A cross-encoder over the top 20 improved rank-1 accuracy but
  hurt whether the right chunk showed up in the top 5 at all, so it was left out.
- **The gate is one global number**, tuned against the sample corpus.
- **Citations are chunk-level, not sentence-level.**
- **No conversation memory.** Each question is independent.
- **We check that citation tags are valid, not that the cited chunk actually
  supports the sentence.** An entailment check would close that gap.
- **CORS is wide open** in [main.py](app/main.py) — fine locally, not for deployment.
