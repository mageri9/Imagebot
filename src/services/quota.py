from datetime import date
from src.core.db import get_db
from src.core.config import get_settings


def _today() -> str:
    return date.today().isoformat()


async def get_usage(user_id: int) -> int:
    """How many generations today."""
    db = await get_db()
    async with db.execute(
        "SELECT count FROM daily_usage WHERE user_id = ? AND date = ?",
        (user_id, _today()),
    ) as cur:
        row = await cur.fetchone()
    return row["count"] if row else 0


async def get_limit(user_id: int) -> int:
    """Per-user limit or default."""
    db = await get_db()
    async with db.execute(
        "SELECT daily_limit FROM users WHERE user_id = ?", (user_id,)
    ) as cur:
        row = await cur.fetchone()
    return row["daily_limit"] if row else get_settings().DEFAULT_DAILY_LIMIT


async def check_quota(user_id: int) -> tuple[bool, int, int]:
    """
    Returns (allowed, used, limit).
    Admins always allowed.
    """
    if user_id in get_settings().ADMIN_IDS:
        return True, 0, 999

    used = await get_usage(user_id)
    limit = await get_limit(user_id)
    return used < limit, used, limit


async def increment_usage(user_id: int) -> None:
    db = await get_db()
    await db.execute(
        """
        INSERT INTO daily_usage (user_id, date, count) VALUES (?, ?, 1)
        ON CONFLICT(user_id, date) DO UPDATE SET count = count + 1
        """,
        (user_id, _today()),
    )
    await db.commit()


async def log_generation(
    user_id: int,
    mode: str,
    model: str,
    prompt: str | None = None,
    success: bool = True,
    error_msg: str | None = None,
) -> None:
    db = await get_db()
    await db.execute(
        """
        INSERT INTO generations (user_id, mode, model, prompt, success, error_msg)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, mode, model, prompt, success, error_msg),
    )
    await db.commit()
