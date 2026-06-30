import aiosqlite
from pathlib import Path
from loguru import logger

from .config import get_settings

_conn: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _conn
    if _conn is None:
        raise RuntimeError("DB not initialized. Call init_db() first.")
    return _conn


async def init_db() -> None:
    global _conn
    settings = get_settings()

    settings.db_path.parent.mkdir(parents=True, exist_ok=True)

    _conn = await aiosqlite.connect(settings.db_path)
    _conn.row_factory = aiosqlite.Row  # доступ по имени колонки

    # Включаем WAL-режим для параллельного чтения и записи
    await _conn.execute("PRAGMA journal_mode=WAL;")
    # Настраиваем задержку ожидания блокировки до 5 секунд
    await _conn.execute("PRAGMA busy_timeout=5000;")
    await _conn.commit()

    schema_path = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
    schema = schema_path.read_text(encoding="utf-8")
    await _conn.executescript(schema)
    await _conn.commit()

    logger.info(f"DB initialized at {settings.db_path} (WAL and busy_timeout enabled)")


async def close_db() -> None:
    global _conn
    if _conn:
        await _conn.close()
        _conn = None
        logger.info("DB connection closed")
