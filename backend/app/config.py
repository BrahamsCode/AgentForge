import json
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://agentforge:agentforge@localhost:5432/agentforge"
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "agentforge"
    s3_secret_key: str = "agentforge-secret"
    s3_bucket: str = "agentforge-workspaces"

    jwt_secret: str = "dev-secret"
    jwt_expires_minutes: int = 1440

    # Aprobaciones human-in-the-loop
    approval_timeout_seconds: int = 900  # 15 min; al agotarse se rechaza la acción
    approval_poll_seconds: float = 2.0

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"

    # Servidores MCP (v2): JSON con lista de {name, url, headers?}
    mcp_servers: list[dict] = []

    @field_validator("mcp_servers", mode="before")
    @classmethod
    def _parse_mcp_servers(cls, value):
        if isinstance(value, str):
            return json.loads(value) if value.strip() else []
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
