from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # API keys — no defaults; must be set in .env for real usage
    odds_api_key: str = ""

    # Runtime environment
    environment: str = "development"

    # CORS: comma-separated list in .env, e.g. "http://localhost:5173,https://myapp.com"
    allowed_origins: str = "http://localhost:5173"

    # Rate limiting
    rate_limit: str = "100/minute"

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        allowed = {"development", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"environment must be one of {allowed}")
        return v

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
