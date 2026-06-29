from src.core.db import get_db


async def get_setting(key: str, fallback: str = "") -> str:
    db = await get_db()
    async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
        row = await cur.fetchone()
    return row["value"] if row else fallback


async def set_setting(key: str, value: str) -> None:
    db = await get_db()
    await db.execute(
        """
        INSERT INTO settings (key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, value),
    )
    await db.commit()


async def get_active_model() -> str:
    from src.core.config import get_settings
    fallback = get_settings().DEFAULT_IMAGE_MODEL
    return await get_setting("image_model", fallback)


async def get_image_params() -> dict:
    """Returns size and quality from DB settings."""
    from src.core.config import get_settings
    cfg = get_settings()
    return {
        "size": await get_setting("image_size", cfg.IMAGE_SIZE),
        "quality": await get_setting("image_quality", cfg.IMAGE_QUALITY),
    }
