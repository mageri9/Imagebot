from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder


# ── Main menu (persistent reply keyboard) ────────────────────────────────────

def main_menu() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="🎨 Сгенерировать"),
        KeyboardButton(text="📊 Остаток"),
    )
    builder.row(
        KeyboardButton(text="❓ Помощь"),
    )
    return builder.as_markup(resize_keyboard=True)


# ── Inline keyboards ──────────────────────────────────────────────────────────

def mode_keyboard(max_multi: int = 3) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✏️ По тексту", callback_data="mode:text"),
        InlineKeyboardButton(text="🖼 По фото", callback_data="mode:image"),
    )
    builder.row(
        InlineKeyboardButton(
            text=f"🖼🖼 По нескольким фото (до {max_multi})",
            callback_data="mode:multi",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="gen:cancel"),
    )
    return builder.as_markup()


def multi_image_keyboard(count: int, max_multi: int = 3) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=f"✅ Готово ({count}/{max_multi}), генерировать",
            callback_data="gen:done",
        ),
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="gen:cancel"),
    )
    return builder.as_markup()


def cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="gen:cancel"))
    return builder.as_markup()
