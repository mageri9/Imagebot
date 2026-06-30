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

def admin_main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👥 Пользователи", callback_data="admin:users"),
        InlineKeyboardButton(text="⚙️ Настройки ИИ", callback_data="admin:settings"),
    )
    builder.row(
        InlineKeyboardButton(text="❌ Закрыть панель", callback_data="admin:close"),
    )
    return builder.as_markup()


def admin_settings_menu(model: str, quality: str, provider: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=f"🤖 Модель: {model}", callback_data="admin:select_model"),
    )
    builder.row(
        InlineKeyboardButton(text=f"✨ Качество: {quality}", callback_data="admin:select_quality"),
    )
    builder.row(
        InlineKeyboardButton(text=f"🔌 Провайдер: {provider}", callback_data="admin:select_provider"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:main"),
    )
    return builder.as_markup()


def admin_model_choice() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Flux-2", callback_data="admin:model:flux"),
        InlineKeyboardButton(text="Midjourney", callback_data="admin:model:midjourney"),
    )
    builder.row(
        InlineKeyboardButton(text="SD 3", callback_data="admin:model:sd3"),
        InlineKeyboardButton(text="GPT-Image 2", callback_data="admin:model:gpt-image-2"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:settings"),
    )
    return builder.as_markup()


def admin_quality_choice() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Low", callback_data="admin:quality:low"),
        InlineKeyboardButton(text="Medium", callback_data="admin:quality:medium"),
        InlineKeyboardButton(text="High", callback_data="admin:quality:high"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:settings"),
    )
    return builder.as_markup()


def admin_provider_choice() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Gen-API", callback_data="admin:provider:genapi"),
        InlineKeyboardButton(text="AITunnel", callback_data="admin:provider:aitunnel"),
    )
    builder.row(
        InlineKeyboardButton(text="Автоматически (Баланс)", callback_data="admin:provider:auto"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:settings"),
    )
    return builder.as_markup()
