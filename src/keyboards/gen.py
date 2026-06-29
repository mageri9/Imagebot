from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def mode_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✏️ По тексту", callback_data="mode:text"),
        InlineKeyboardButton(text="🖼 По фото", callback_data="mode:image"),
    )
    builder.row(
        InlineKeyboardButton(text="🖼🖼 По нескольким фото", callback_data="mode:multi"),
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="gen:cancel"),
    )
    return builder.as_markup()


def multi_image_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Готово, генерировать", callback_data="gen:done"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="gen:cancel"),
    )
    return builder.as_markup()


def cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="gen:cancel"))
    return builder.as_markup()
