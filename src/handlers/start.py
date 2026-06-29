import html
from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from src.services.quota import check_quota

router = Router()


async def cmd_start(message: Message):
    _, used, limit = await check_quota(message.from_user.id)
    await message.answer(
        f"👋 Привет, {html.escape(message.from_user.full_name)}!\n\n"
        f"Я генерирую картинки по тексту и фотографиям.\n\n"
        f"📊 Сегодня использовано: {used}/{limit}\n\n"
        f"Команды:\n"
        f"/gen — сгенерировать картинку\n"
        f"/help — помощь"
    )


async def cmd_help(message: Message):
    await message.answer(
        "🎨 <b>Как пользоваться:</b>\n\n"
        "1. /gen — запускает генерацию\n"
        "2. Выбери режим:\n"
        "   • <b>По тексту</b> — просто опиши картинку\n"
        "   • <b>По фото</b> — отправь фото + промпт\n"
        "   • <b>По нескольким фото</b> — до 5 фото + промпт\n\n"
        "/cancel — отменить текущее действие"
    )


def register_handlers():
    router.message.register(cmd_start, CommandStart())
    router.message.register(cmd_help, Command("help"))
