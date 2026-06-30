import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery, User
from loguru import logger


class ThrottleMiddleware(BaseMiddleware):
    """
    Простой антифлуд: не чаще одного апдейта от пользователя за `rate_limit` секунд.
    Не персистентный (in-memory) — переживает только в рамках одного запуска процесса,
    этого достаточно для защиты от спама кнопками/сообщениями.
    """

    def __init__(self, rate_limit: float = 1.0):
        self.rate_limit = rate_limit
        self._last_seen: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        now = time.monotonic()
        last = self._last_seen.get(user.id)
        self._last_seen[user.id] = now

        if last is not None and (now - last) < self.rate_limit:
            logger.warning(f"[throttle] user_id={user.id} flooding, ignored")
            if isinstance(event, CallbackQuery):
                await event.answer("⏳ Слишком быстро, подожди секунду.", show_alert=False)
            elif isinstance(event, Message):
                pass  # молча игнорируем, не спамим ответом на спам
            return None

        return await handler(event, data)