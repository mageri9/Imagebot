from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Bot
    BOT_TOKEN: str
    ADMIN_IDS: list[int]

    # Provider (any OpenAI-compatible API)
    PROVIDER_BASE_URL: str
    PROVIDER_API_KEY: str

    # Model — stored here as default, can be overridden in DB later
    DEFAULT_IMAGE_MODEL: str = "gpt-image-1"

    # Generation defaults
    IMAGE_SIZE: str = "1024x1024"
    IMAGE_QUALITY: str = "medium"

    # Quota
    DEFAULT_DAILY_LIMIT: int = 10

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
