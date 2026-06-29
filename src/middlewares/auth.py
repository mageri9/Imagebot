from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from loguru import logger

from src.services.user import is_allowed


class WhitelistMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        if not await is_allowed(user.id):
            logger.warning(f"Unauthorized access attempt: user_id={user.id} username={user.username}")
            if isinstance(event, Message):
                await event.answer("⛔ У вас нет доступа к этому боту.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔ Нет доступа.", show_alert=True)
            return None

        return await handler(event, data)
