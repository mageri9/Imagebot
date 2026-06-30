from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Bot
    BOT_TOKEN: str
    ADMIN_IDS: list[int]

    # Provider
    PROVIDER_TYPE: str = "openai_compat"  # openai_compat | genapi
    PROVIDER_BASE_URL: str = ""
    PROVIDER_API_KEY: str = ""

    # Gen-API native provider
    GENAPI_BASE_URL: str = "https://api.gen-api.ru"
    GENAPI_API_KEY: str = ""

    # Model — default, overridden from DB at runtime
    DEFAULT_IMAGE_MODEL: str = "gpt-image-1"

    # Generation defaults (also overridden from DB)
    IMAGE_SIZE: str = "1024x1024"
    IMAGE_QUALITY: str = "medium"

    # Multi-image mode
    MAX_MULTI_IMAGES: int = 3

    # Quota
    DEFAULT_DAILY_LIMIT: int = 10

    # Redis (FSM storage)
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""

    # Logging
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = Path(__file__).resolve().parents[2] / ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v):
        if isinstance(v, str):
            import json
            return json.loads(v)
        return v

    @property
    def db_path(self) -> Path:
        return Path(__file__).resolve().parents[2] / "data" / "bot.db"

    @property
    def redis_url(self) -> str:
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
