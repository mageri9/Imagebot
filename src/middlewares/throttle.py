from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery, User
from redis.asyncio import Redis
from loguru import logger


class ThrottleMiddleware(BaseMiddleware):
    """
    Простой антифлуд: не чаще одного апдейта от пользователя за `rate_limit` секунд.
    Состояние хранится в Redis (SET key NX PX <rate_limit_ms>), поэтому лимит
    общий для всех инстансов бота при горизонтальном масштабировании и переживает
    рестарт процесса.
    """

    def __init__(self, redis: Redis, rate_limit: float = 1.0):
        self._redis = redis
        self.rate_limit = rate_limit
        self._last_seen: dict[int, float] = {}

    @staticmethod
    def _key(user_id: int) -> str:
        return f"throttle:{user_id}"

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        # SET ... NX PX ставит ключ только если его ещё нет — атомарно и без гонок
        # между параллельными апдейтами того же пользователя на разных инстансах.
        acquired = await self._redis.set(
            self._key(user.id),
            "1",
            px=int(self.rate_limit * 1000),
            nx=True,
        )
        if not acquired:
            logger.warning(f"[throttle] user_id={user.id} flooding, ignored")
            if isinstance(event, CallbackQuery):
                await event.answer("⏳ Слишком быстро, подожди секунду.", show_alert=False)
            elif isinstance(event, Message):
                pass  # молча игнорируем, не спамим ответом на спам
            return None

        return await handler(event, data)