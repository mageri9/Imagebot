from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from loguru import logger

from src.core.config import get_settings
from src.services.user import get_user, add_user


class WhitelistMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        # Админы всегда проходят
        if user.id in get_settings().ADMIN_IDS:
            return await handler(event, data)

        existing = await get_user(user.id)
        if existing is None:
            # Новый пользователь — авторегистрация с лимитом 1/день
            await add_user(
                user_id=user.id,
                username=user.username,
                full_name=user.full_name,
                added_by=0,  # 0 = самостоятельная регистрация
                daily_limit=1,
            )
            logger.info(f"New user auto-registered: id={user.id} username={user.username}")
        elif not existing["is_active"]:
            # Деактивированный пользователь — не пускаем
            if isinstance(event, Message):
                await event.answer("⛔ Ваш аккаунт деактивирован. Обратитесь к администратору.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔ Аккаунт деактивирован.", show_alert=True)
            return None

        return await handler(event, data)
