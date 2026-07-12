import asyncio
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis
from loguru import logger

from src.core.config import get_settings
from src.core.db import init_db, close_db
from src.core.router_manager import setup_routers
from src.core.redis import get_redis, close_redis
from src.middlewares.auth import WhitelistMiddleware
from src.middlewares.logger import LoggerMiddleware
from src.middlewares.throttle import ThrottleMiddleware


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

    logger.info(f"Connecting to Redis at {settings.REDIS_HOST}:{settings.REDIS_PORT}...")
    redis = get_redis()
    await redis.ping()
    storage = RedisStorage(redis=redis)

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=storage)

    # --- ИНТЕГРАЦИЯ NEXUS SDK ---
    from os import environ
    nexus_sdk = None
    nexus_secret = environ.get("NEXUS_APP_SECRET", "")
    nexus_url = environ.get("NEXUS_ENDPOINT_URL", "http://nexus-webhook:8000/events/app")

    if nexus_secret:
        try:
            from nexus_sdk import NexusSDK
            nexus_sdk = NexusSDK(
                endpoint_url=nexus_url,
                app_secret=nexus_secret,
                project_name="imagebot"  # Должно строго совпадать с именем в manifests
            )
            # 1. Регистрируем глобальный перехватчик исключений aiogram
            nexus_sdk.register_aiogram_error_handler(dp)
            # 2. Запускаем периодическую отправку пульса (Heartbeat) каждые 15 секунд
            nexus_sdk.start_heartbeat(interval_seconds=15)
            logger.info("📡 Nexus SDK Observability initialized successfully (Heartbeat & Error Handler)")
        except Exception as e:
            logger.error(f"Failed to initialize Nexus SDK: {e}")
    else:
        logger.warning("⚠️ NEXUS_APP_SECRET is not set in environment. Nexus SDK is disabled.")
    # ----------------------------

    dp.update.outer_middleware(ThrottleMiddleware(redis=redis, rate_limit=0.7))
    dp.update.outer_middleware(LoggerMiddleware())
    dp.update.outer_middleware(WhitelistMiddleware())

    router = setup_routers()
    dp.include_router(router)

    bot_info = await bot.get_me()
    logger.info(f"Bot started: @{bot_info.username} (id={bot_info.id})")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        # Грациозно останавливаем фоновые процессы SDK при выключении бота
        if nexus_sdk:
            await nexus_sdk.close()

        from src.services.image_gen import PROVIDER_POOL

        for prov_config in PROVIDER_POOL:
            prov = prov_config["provider"]
            if hasattr(prov, "close"):
                await prov.close()
        await close_db()
        await close_redis()
        await bot.session.close()
        logger.info("Bot stopped.")


def cli():
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    cli()