import math

from app.services.chunk_service import embed_text

# Balance between relevance and diversity. 1.0 = pure relevance (same
# order as plain dense search); 0.0 = pure diversity (ignores the
# question entirely). 0.5 is a neutral middle ground.
MMR_LAMBDA = 0.5


def _cosine(a: list[float], b: list[float]) -> float:

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


def mmr_select(
    query_embedding: list[float],
    hits: list[dict],
    embedding_service,
    top_k: int,
    lambda_param: float = MMR_LAMBDA,
) -> list[dict]:
    """
    Maximal Marginal Relevance: greedily pick chunks that are relevant
    to the query but not too similar to what's already been picked,
    so the top-k isn't dominated by several near-duplicate chunks
    all saying the same thing. Reorders and re-selects from `hits`
    (which should already be a widened dense candidate pool) - it
    never introduces a chunk the first-pass search missed.

    Each step picks the candidate maximising:
        lambda * relevance_to_query - (1 - lambda) * max_similarity_to_already_picked
    """

    if not hits:
        return hits[:top_k]

    candidate_embeddings = embedding_service.generate_embeddings(
        [embed_text(hit) for hit in hits]
    )

    remaining = list(range(len(hits)))
    selected: list[int] = []

    while remaining and len(selected) < top_k:

        best_index = None
        best_score = float("-inf")

        for i in remaining:

            relevance = _cosine(query_embedding, candidate_embeddings[i])

            if selected:
                diversity_penalty = max(
                    _cosine(candidate_embeddings[i], candidate_embeddings[j])
                    for j in selected
                )
            else:
                diversity_penalty = 0.0

            mmr_score = lambda_param * relevance - (1 - lambda_param) * diversity_penalty

            if mmr_score > best_score:
                best_score = mmr_score
                best_index = i

        selected.append(best_index)
        remaining.remove(best_index)

    return [hits[i] for i in selected]
