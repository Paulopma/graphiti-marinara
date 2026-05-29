from functools import lru_cache

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = Field(..., min_length=1)

    deepseek_api_key: str = Field(..., min_length=1)
    deepseek_base_url: HttpUrl = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_small_model: str = "deepseek-chat"

    marinara_host: HttpUrl = "http://host.docker.internal:7860"
    embedding_provider: str = "openai_compatible"
    embedding_api_key: str | None = None
    embedding_base_url: HttpUrl = "https://openrouter.ai/api/v1"
    embedding_model: str = "qwen/qwen3-embedding-8b"
    embedding_dimension: int = 4096
    embedding_timeout_seconds: float = 10.0

    graphiti_api_port: int = 8765
    log_level: str = "INFO"
    graphiti_store_raw_episode_content: bool = True
    graphiti_update_communities: bool = False
    graphiti_startup_timeout_seconds: float = 30.0
    neo4j_health_timeout_seconds: float = 5.0
    search_default_limit: int = 10
    search_max_limit: int = 25
    health_llm_timeout_seconds: float = 15.0

    @property
    def embeddings_url(self) -> str:
        return f"{str(self.marinara_host).rstrip('/')}/api/sidecar/v1/embeddings"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
