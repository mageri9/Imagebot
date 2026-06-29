from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User
from loguru import logger


class LoggerMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        tag = f"(@{user.username})" if user.username else ""

        if event.message is not None:
            text = event.message.text or event.message.caption or "[media]"
            logger.info(f'[MSG] "{text}" | {user.full_name} {tag} | id={user.id}')
        elif event.callback_query is not None:
            logger.info(f'[CB] "{event.callback_query.data}" | {user.full_name} {tag} | id={user.id}')

        return await handler(event, data)
