import os
from pathlib import Path

import pytest
import pytest_asyncio
import aiosqlite

# Обязательные для pydantic Settings переменные — выставляем до любого импорта config,
# чтобы Settings() не падал с ValidationError при первом обращении к get_settings().
os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ADMIN_IDS", "[999]")

import src.core.db as db_module
from src.core.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """get_settings() кэширован через lru_cache — сбрасываем между тестами,
    чтобы monkeypatch.setenv в одном тесте не утекал в соседние."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def memory_db():
    """
    In-memory SQLite с применённой схемой, подставленная как глобальное
    соединение src.core.db._conn — так тестируемый код (quota.py, user.py и т.д.)
    получает соединение через обычный get_db() без изменений.
    """
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row

    schema_path = Path(__file__).resolve().parents[1] / "src" / "db" / "schema.sql"
    schema = schema_path.read_text(encoding="utf-8")
    await conn.executescript(schema)
    await conn.commit()

    db_module._conn = conn
    yield conn

    await conn.close()
    db_module._conn = None