import asyncio
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from loguru import logger

from src.core.config import get_settings
from src.core.db import init_db, close_db
from src.core.router_manager import setup_routers
from src.middlewares.auth import WhitelistMiddleware
from src.middlewares.logger import LoggerMiddleware
from src.providers.registry import init_provider


async def main():
    settings = get_settings()

    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | {message}",
        level=settings.LOG_LEVEL,
        colorize=True,
    )
    logger.add(
        "logs/bot.log",
        rotation="10 MB",
        retention="7 days",
        compression="zip",
        level="DEBUG",
    )

    logger.info("Initializing DB...")
    await init_db()

    logger.info("Initializing provider...")
    init_provider()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())

    dp.update.outer_middleware(LoggerMiddleware())
    dp.update.outer_middleware(WhitelistMiddleware())

    router = setup_routers()
    dp.include_router(router)

    bot_info = await bot.get_me()
    logger.info(f"Bot started: @{bot_info.username} (id={bot_info.id})")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await close_db()
        await bot.session.close()
        logger.info("Bot stopped.")


def cli():
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    cli()
