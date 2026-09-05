"""
The one place that names the retrieval modes and chunking strategies the
application offers, with the labels and explanations the UI shows. Served by
GET /api/v1/settings so the frontend never hard-codes them.
"""

RETRIEVAL_MODES = [
    {
        "id": "dense",
        "label": "Meaning (dense)",
        "description": "Embedding similarity only. Fast and the measured default.",
        "requires_llm": False,
    },
    {
        "id": "hybrid",
        "label": "Meaning + keyword (hybrid)",
        "description": (
            "Dense search fused with BM25 keyword ranking (reciprocal rank fusion). "
            "Best for exact identifiers such as endorsement codes."
        ),
        "requires_llm": False,
    },
    {
        "id": "rerank",
        "label": "Reranked (cross-encoder)",
        "description": (
            "Fetches 25 dense candidates and re-scores each with a cross-encoder. "
            "Slower; the model downloads on first use."
        ),
        "requires_llm": False,
    },
    {
        "id": "mmr",
        "label": "Diverse (MMR)",
        "description": "Maximal marginal relevance: relevant chunks that are not near-duplicates of each other.",
        "requires_llm": False,
    },
    {
        "id": "rewrite",
        "label": "Rewritten query",
        "description": "The language model rewrites the question into a cleaner search query before searching.",
        "requires_llm": True,
    },
    {
        "id": "hyde",
        "label": "HyDE",
        "description": "The language model drafts a hypothetical answer passage, which is embedded instead of the question.",
        "requires_llm": True,
    },
]

CHUNK_STRATEGIES = [
    {
        "id": "heading",
        "label": "By heading",
        "description": (
            "One chunk per detected section (markdown, SECTION/ARTICLE, or numbered headings). "
            "Falls back to fixed-size windows for documents with no structure."
        ),
    },
    {
        "id": "fixed_size",
        "label": "Fixed size",
        "description": "Overlapping windows of 300 words with a 50-word overlap, ignoring structure.",
    },
]

MODE_IDS = tuple(mode["id"] for mode in RETRIEVAL_MODES)
STRATEGY_IDS = tuple(strategy["id"] for strategy in CHUNK_STRATEGIES)
