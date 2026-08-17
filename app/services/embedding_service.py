from app.core.config import settings

# Embedding models are trained asymmetrically: questions and passages get
# different instruction prefixes. Using the wrong one costs accuracy
# silently, so it lives beside the model name. Only the model actually
# configured in EMBEDDING_MODEL is listed - switching models requires
# adding its correct prefix here too, on purpose (see README.md's model
# comparison for the values other candidates used).
PREFIXES = {
    # model: (question prefix, passage prefix)
    "BAAI/bge-small-en-v1.5": (
        "Represent this sentence for searching relevant passages: ", ""
    ),
}

_models: dict = {}


class EmbeddingService:
    """
    Service responsible for generating embeddings.

    This is a bi-encoder: questions and chunks are embedded separately,
    so every chunk vector is computed once at ingest and reused.
    """

    def __init__(self, model_name: str | None = None):

        self.model_name = model_name or settings.EMBEDDING_MODEL

    def load(self):
        """
        Load the model once. The first call downloads the weights.
        """

        if self.model_name not in _models:

            from fastembed import TextEmbedding

            _models[self.model_name] = TextEmbedding(
                model_name=self.model_name
            )

        return _models[self.model_name]

    def dimension(self) -> int:
        """
        Vector size, read from the registry so the model need not load.
        """

        from fastembed import TextEmbedding

        for description in TextEmbedding.list_supported_models():

            if description["model"] == self.model_name:
                return int(description["dim"])

        raise ValueError(f"Unknown embedding model: {self.model_name}")

    def generate_embeddings(self, texts: list[str]) -> list[list[float]]:

        if not texts:
            return []

        prefix = PREFIXES.get(self.model_name, ("", ""))[1]

        prepared = [prefix + text for text in texts] if prefix else texts

        return [
            vector.tolist()
            for vector in self.load().embed(prepared, batch_size=64)
        ]

    def generate_query_embedding(self, text: str) -> list[float]:

        prefix = PREFIXES.get(self.model_name, ("", ""))[0]

        return next(
            iter(self.load().embed([prefix + text]))
        ).tolist()