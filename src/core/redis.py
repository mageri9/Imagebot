from redis.asyncio import Redis
from src.core.config import get_settings

_redis_client: Redis | None = None


def get_redis() -> Redis:
    """Возвращает существующий клиент Redis или инициализирует новый."""
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis_client


async def close_redis() -> None:
    """Безопасно закрывает глобальное подключение к Redis."""
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None