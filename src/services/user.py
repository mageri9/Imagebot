from aiosqlite import Row
from src.core.db import get_db
from src.core.config import get_settings


async def get_user(user_id: int) -> Row | None:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM users WHERE user_id = ?", (user_id,)
    ) as cur:
        return await cur.fetchone()


async def is_allowed(user_id: int) -> bool:
    """Check whitelist: either admin or active user in DB."""
    if user_id in get_settings().ADMIN_IDS:
        return True
    user = await get_user(user_id)
    return user is not None and bool(user["is_active"])


async def add_user(
    user_id: int,
    username: str | None,
    full_name: str | None,
    added_by: int,
    daily_limit: int | None = None,
) -> bool:
    """Returns True if added, False if already exists."""
    db = await get_db()
    limit = daily_limit or get_settings().DEFAULT_DAILY_LIMIT

    existing = await get_user(user_id)
    if existing:
        # Reactivate if was deactivated
        await db.execute(
            "UPDATE users SET is_active = 1 WHERE user_id = ?", (user_id,)
        )
        await db.commit()
        return False

    await db.execute(
        """
        INSERT INTO users (user_id, username, full_name, daily_limit, added_by)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, username, full_name, limit, added_by),
    )
    await db.commit()
    return True


async def remove_user(user_id: int) -> bool:
    """Soft delete — sets is_active=0."""
    db = await get_db()
    user = await get_user(user_id)
    if not user:
        return False
    await db.execute(
        "UPDATE users SET is_active = 0 WHERE user_id = ?", (user_id,)
    )
    await db.commit()
    return True


async def set_user_limit(user_id: int, limit: int) -> bool:
    db = await get_db()
    user = await get_user(user_id)
    if not user:
        return False
    await db.execute(
        "UPDATE users SET daily_limit = ? WHERE user_id = ?", (limit, user_id)
    )
    await db.commit()
    return True


async def list_users() -> list[Row]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM users WHERE is_active = 1 ORDER BY added_at DESC"
    ) as cur:
        return await cur.fetchall()
