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


VALID_SIZES = {"1024x1024", "1792x1024", "1024x1792", "1024x768"}

# Принудительный потолок цены: что бы ни было записано в БД, дороже "low" не уходит.
FORCED_MAX_QUALITY = "low"


async def get_image_params() -> dict:
    """
    Returns size and quality from DB settings, validated against known values.
    Quality жёстко зафиксирован на самом дешёвом тарифе ("low") — это сделано
    намеренно, чтобы исключить случайные траты на medium/high из-за бага в коде
    или ручной правки БД.
    """
    from loguru import logger
    from src.core.config import get_settings
    cfg = get_settings()

    size = await get_setting("image_size", cfg.IMAGE_SIZE)
    if size not in VALID_SIZES:
        logger.warning(
            f"[settings] Invalid image_size '{size}' in DB, "
            f"falling back to default '{cfg.IMAGE_SIZE}'"
        )
        size = cfg.IMAGE_SIZE

    return {
        "size": size,
        "quality": FORCED_MAX_QUALITY,
    }
