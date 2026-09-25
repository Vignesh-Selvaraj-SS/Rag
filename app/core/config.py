from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """
    All runtime configuration, read from the environment / `.env`.

    Every value has a working local default except GROQ_API_KEY: without it
    ingestion and retrieval still run, only answer generation is disabled
    (the API reports this as a 503 with a clear message).
    """

    # --- language model ---------------------------------------------------
    GROQ_API_KEY: str = ""
    MODEL_NAME: str = "llama-3.3-70b-versatile"

    # --- retrieval ----------------------------------------------------------
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    QDRANT_PATH: str = str(PROJECT_ROOT / ".qdrant")
    COLLECTION_NAME: str = "insurance_claims"
    TOP_K: int = 5
    MIN_SCORE: float = 0.60

    # --- storage ------------------------------------------------------------
    DATA_DIR: Path = PROJECT_ROOT / "data"
    EVALUATION_DIR: Path = PROJECT_ROOT / "evaluation"
    RUNTIME_DIR: Path = PROJECT_ROOT / ".runtime"
    RECORD_TRACES: bool = True
    MAX_UPLOAD_MB: int = 20

    # --- web ----------------------------------------------------------------
    CORS_ORIGINS: str = "http://localhost:4200,http://127.0.0.1:4200"
    FRONTEND_DIST: Path = PROJECT_ROOT / "frontend" / "dist" / "rag-assistant" / "browser"
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        extra="ignore",
    )

    @field_validator("TOP_K")
    @classmethod
    def _top_k_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("TOP_K must be at least 1")
        return value

    @field_validator("MIN_SCORE")
    @classmethod
    def _min_score_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("MIN_SCORE must be between 0 and 1")
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def golden_set_path(self) -> Path:
        return self.EVALUATION_DIR / "golden_set.jsonl"

    @property
    def evaluation_runs_dir(self) -> Path:
        return self.RUNTIME_DIR / "evaluations"

    @property
    def eval_set_path(self) -> Path:
        """The Week 6 answer-quality test set, scored by scripts/run_evals.py."""
        return self.EVALUATION_DIR / "eval_set.jsonl"

    @property
    def eval_runs_dir(self) -> Path:
        return self.RUNTIME_DIR / "evals"

    @property
    def judge_dir(self) -> Path:
        """Judge validation artefacts: generated summaries and grading sheets."""
        return self.RUNTIME_DIR / "judge"

    @property
    def traces_path(self) -> Path:
        return self.RUNTIME_DIR / "traces.jsonl"

    @property
    def index_metadata_path(self) -> Path:
        return Path(self.QDRANT_PATH) / "index_meta.json"

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024

    @property
    def llm_configured(self) -> bool:
        return bool(self.GROQ_API_KEY)


settings = Settings()

# Kept as a module constant because the ingestion and evaluation services
# refer to the corpus folder directly.
DATA_DIR = settings.DATA_DIR
