"""Central configuration, loaded from environment variables / .env."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    # SEC requires a descriptive User-Agent with a contact email:
    # https://www.sec.gov/os/accessing-edgar-data
    sec_user_agent: str = "FinRAG portfolio project contact@example.com"

    data_dir: Path = PROJECT_ROOT / "data"

    # Local embedding model (free, CPU). Its 512-token limit drives chunk sizing.
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_max_tokens: int = 512
    reranker_model: str = "BAAI/bge-reranker-base"
    # "auto" = mps on Apple Silicon, cuda if available, else cpu. Override with DEVICE=cpu.
    device: str = "auto"

    # Free-tier LLM providers; embeddings and reranking run locally
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"

    @property
    def raw_sec_dir(self) -> Path:
        return self.data_dir / "raw" / "sec"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "indexes"


@lru_cache
def get_settings() -> Settings:
    return Settings()
