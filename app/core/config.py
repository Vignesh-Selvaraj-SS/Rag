from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"


class Settings(BaseSettings):
    GROQ_API_KEY: str
    MODEL_NAME: str
    EMBEDDING_MODEL: str
    QDRANT_PATH: str
    COLLECTION_NAME: str
    TOP_K: int
    MIN_SCORE: float

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )


settings = Settings()
