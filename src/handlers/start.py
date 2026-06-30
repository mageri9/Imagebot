import html
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from src.keyboards.gen import main_menu
from src.services.quota import check_quota

router = Router()


async def cmd_start(message: Message):
    _, used, limit = await check_quota(message.from_user.id)
    await message.answer(
        f"👋 Привет, {html.escape(message.from_user.full_name)}!\n\n"
        f"Я генерирую картинки по тексту и фотографиям.\n\n"
        f"📊 Сегодня использовано: <b>{used}/{limit}</b>",
        reply_markup=main_menu(),
    )


async def cmd_help(message: Message):
    await message.answer(
        "🎨 <b>Как пользоваться:</b>\n\n"
        "Нажми кнопку <b>🎨 Сгенерировать</b> или /gen и выбери режим:\n\n"
        "• <b>По тексту</b> — опиши что хочешь получить\n"
        "• <b>По фото</b> — отправь фото и скажи что изменить\n"
        "• <b>По нескольким фото</b> — загрузи несколько фото + промпт\n\n"
        "<b>❌ Отмена</b> — кнопка под любым шагом или /cancel",
        reply_markup=main_menu(),
    )


async def btn_quota(message: Message):
    _, used, limit = await check_quota(message.from_user.id)
    await message.answer(f"📊 Использовано сегодня: <b>{used}/{limit}</b>")


def register_handlers():
    router.message.register(cmd_start, CommandStart())
    router.message.register(cmd_help, Command("help"))
    router.message.register(cmd_help, F.text == "❓ Помощь")
    router.message.register(btn_quota, F.text == "📊 Остаток")
