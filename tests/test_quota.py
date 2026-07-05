import pytest

from src.services.quota import (
    try_consume_quota,
    release_quota,
    get_usage,
    check_quota,
)


@pytest.mark.asyncio
async def test_try_consume_quota_allows_within_limit(memory_db, monkeypatch):
    user_id = 1
    await memory_db.execute(
        "INSERT INTO users (user_id, daily_limit) VALUES (?, ?)", (user_id, 2)
    )
    await memory_db.commit()

    allowed, used, limit = await try_consume_quota(user_id)
    assert allowed is True
    assert used == 1
    assert limit == 2

    allowed, used, limit = await try_consume_quota(user_id)
    assert allowed is True
    assert used == 2


@pytest.mark.asyncio
async def test_try_consume_quota_blocks_at_limit(memory_db):
    user_id = 2
    await memory_db.execute(
        "INSERT INTO users (user_id, daily_limit) VALUES (?, ?)", (user_id, 1)
    )
    await memory_db.commit()

    allowed, used, limit = await try_consume_quota(user_id)
    assert allowed is True
    assert used == 1

    # Второй запрос должен быть отклонён и НЕ должен увеличивать счётчик дальше
    allowed, used, limit = await try_consume_quota(user_id)
    assert allowed is False
    assert used == 1  # не выросло сверх лимита
    assert limit == 1


@pytest.mark.asyncio
async def test_try_consume_quota_admin_bypasses_limit(memory_db, monkeypatch):
    from src.core import config

    config.get_settings.cache_clear()
    monkeypatch.setenv("ADMIN_IDS", "[42]")
    config.get_settings.cache_clear()

    allowed, used, limit = await try_consume_quota(42)
    assert allowed is True
    assert limit == 999

    # Ничего не должно быть записано в daily_usage для админа
    assert await get_usage(42) == 0


@pytest.mark.asyncio
async def test_release_quota_decrements_but_not_below_zero(memory_db):
    user_id = 3
    await memory_db.execute(
        "INSERT INTO users (user_id, daily_limit) VALUES (?, ?)", (user_id, 5)
    )
    await memory_db.commit()

    await try_consume_quota(user_id)
    assert await get_usage(user_id) == 1

    await release_quota(user_id)
    assert await get_usage(user_id) == 0

    # Повторный release не должен уйти в минус
    await release_quota(user_id)
    assert await get_usage(user_id) == 0


@pytest.mark.asyncio
async def test_check_quota_is_soft_and_does_not_reserve(memory_db):
    user_id = 4
    await memory_db.execute(
        "INSERT INTO users (user_id, daily_limit) VALUES (?, ?)", (user_id, 3)
    )
    await memory_db.commit()

    allowed, used, limit = await check_quota(user_id)
    assert allowed is True
    assert used == 0  # check_quota не резервирует слот

    assert await get_usage(user_id) == 0