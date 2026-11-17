from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    redis_url: str
    celery_result_backend: str
    llm_base_url: str
    llm_model: str
    llm_api_key: str = "lm-studio"
    llm_mode: str = "lmstudio"  # lmstudio or mock
    llm_timeout_seconds: float = 90.0
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    @field_validator("llm_mode")
    @classmethod
    def valid_llm_mode(cls, value: str) -> str:
        if value not in ("lmstudio", "mock"):
            raise ValueError("LLM_MODE must be lmstudio or mock")
        return value

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
