import html
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.filters.check_admin import IsAdmin
from src.services.user import add_user, remove_user, list_users, set_user_limit
from src.services.settings import (
    get_active_model,
    set_setting,
    get_image_params,
    get_setting,
)
from src.services.quota import get_usage
from src.keyboards.gen import (
    admin_main_menu,
    admin_settings_menu,
    admin_model_choice,
    admin_quality_choice,
    admin_provider_choice,
)

router = Router()


# ── Вспомогательные хелперы ──────────────────────────────────────────────────


async def _get_settings_summary() -> tuple[str, str, str]:
    model = await get_active_model()
    params = await get_image_params()
    provider = await get_setting("provider_type", "auto")
    return model, params["quality"], provider


# ── Интерактивная админ-панель (Inline UI) ───────────────────────────────────


async def cmd_admin(message: Message):
    await message.answer(
        "👑 <b>Админ-панель ImageBot</b>\n\n"
        "Управляйте пользователями, лимитами и настройками ИИ кнопками ниже:",
        reply_markup=admin_main_menu(),
    )


async def cb_admin_main(query: CallbackQuery):
    await query.answer()
    await query.message.edit_text(
        "👑 <b>Админ-панель ImageBot</b>\n\n"
        "Управляйте пользователями, лимитами и настройками ИИ кнопками ниже:",
        reply_markup=admin_main_menu(),
    )


async def cb_admin_close(query: CallbackQuery):
    await query.answer()
    await query.message.edit_text("👑 Админ-панель закрыта.")


async def cb_admin_users(query: CallbackQuery):
    await query.answer()
    users = await list_users()
    if not users:
        await query.message.edit_text(
            "Нет активных пользователей.", reply_markup=admin_main_menu()
        )
        return

    lines = ["👥 <b>Активные пользователи:</b>\n"]
    for u in users:
        used = await get_usage(u["user_id"])
        name = html.escape(u["full_name"] or "—")
        username = f"@{u['username']}" if u["username"] else "—"
        lines.append(
            f"• <code>{u['user_id']}</code> {name} ({username})\n"
            f"  Лимит: {used}/{u['daily_limit']} сегодня\n"
        )

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:main"))

    await query.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())


async def cb_admin_settings(query: CallbackQuery):
    await query.answer()
    model, quality, provider = await _get_settings_summary()
    await query.message.edit_text(
        "⚙️ <b>Настройки генерации ИИ:</b>\n\nНажмите на любой пункт для изменения:",
        reply_markup=admin_settings_menu(model, quality, provider),
    )


# ── Шаги выбора настроек ─────────────────────────────────────────────────────


async def cb_select_model(query: CallbackQuery):
    await query.answer()
    await query.message.edit_text(
        "🤖 <b>Выберите модель по умолчанию:</b>", reply_markup=admin_model_choice()
    )


async def cb_select_quality(query: CallbackQuery):
    await query.answer()
    await query.message.edit_text(
        "✨ <b>Выберите качество генерации:</b>", reply_markup=admin_quality_choice()
    )


async def cb_select_provider(query: CallbackQuery):
    await query.answer()
    await query.message.edit_text(
        "🔌 <b>Выберите ИИ-провайдера:</b>", reply_markup=admin_provider_choice()
    )


# ── Действия сохранения настроек в БД ────────────────────────────────────────


async def cb_save_model(query: CallbackQuery):
    model_name = query.data.split(":")[-1]
    await set_setting("image_model", model_name)
    await query.answer(f"Модель изменена на {model_name}")
    await cb_admin_settings(query)


async def cb_save_quality(query: CallbackQuery):
    quality_val = query.data.split(":")[-1]
    await set_setting("image_quality", quality_val)
    await query.answer(f"Качество изменено на {quality_val}")
    await cb_admin_settings(query)


async def cb_save_provider(query: CallbackQuery):
    provider_val = query.data.split(":")[-1]
    await set_setting("provider_type", provider_val)
    await query.answer(f"Провайдер изменен на {provider_val}")
    await cb_admin_settings(query)


# ── Обратная совместимость с текстовыми командами ───────────────────────────


async def cmd_add_user(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /adduser &lt;user_id&gt; [limit]")
        return

    try:
        user_id = int(parts[1])
        limit = int(parts[2]) if len(parts) > 2 else None
    except ValueError:
        await message.answer("❌ Неверный формат. user_id и limit должны быть числами.")
        return

    added = await add_user(
        user_id=user_id,
        username=None,
        full_name=None,
        added_by=message.from_user.id,
        daily_limit=limit,
    )
    if added:
        await message.answer(f"✅ Пользователь {user_id} добавлен.")
    else:
        await message.answer(
            f"ℹ️ Пользователь {user_id} уже существует (переактивирован)."
        )


async def cmd_remove_user(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /removeuser &lt;user_id&gt;")
        return

    try:
        user_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Неверный user_id.")
        return

    removed = await remove_user(user_id)
    if removed:
        await message.answer(f"✅ Пользователь {user_id} деактивирован.")
    else:
        await message.answer(f"❌ Пользователь {user_id} не найден.")


async def cmd_set_limit(message: Message):
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Использование: /setlimit &lt;user_id&gt; &lt;limit&gt;")
        return

    try:
        user_id, limit = int(parts[1]), int(parts[2])
    except ValueError:
        await message.answer("❌ Неверный формат.")
        return

    ok = await set_user_limit(user_id, limit)
    if ok:
        await message.answer(f"✅ Лимит для {user_id} установлен: {limit}/день.")
    else:
        await message.answer(f"❌ Пользователь {user_id} не найден.")


async def cmd_set_provider(message: Message):
    parts = message.text.split()
    if len(parts) < 2 or parts[1].lower() not in ("genapi", "aitunnel", "auto"):
        await message.answer("Использование: /setprovider &lt;genapi|aitunnel|auto&gt;")
        return

    ptype = parts[1].lower()
    await set_setting("provider_type", ptype)
    await message.answer(
        f"✅ Предпочтительный провайдер установлен: <code>{ptype}</code>"
    )


def register_handlers():
    is_admin = IsAdmin()

    # Регистрация текстовых команд (резервных)
    router.message.register(cmd_admin, Command("admin"), is_admin)
    router.message.register(cmd_add_user, Command("adduser"), is_admin)
    router.message.register(cmd_remove_user, Command("removeuser"), is_admin)
    router.message.register(cmd_set_limit, Command("setlimit"), is_admin)
    router.message.register(cmd_set_provider, Command("setprovider"), is_admin)

    # Регистрация Inline коллбэков админки
    router.callback_query.register(cb_admin_main, F.data == "admin:main", is_admin)
    router.callback_query.register(cb_admin_close, F.data == "admin:close", is_admin)
    router.callback_query.register(cb_admin_users, F.data == "admin:users", is_admin)
    router.callback_query.register(
        cb_admin_settings, F.data == "admin:settings", is_admin
    )

    router.callback_query.register(
        cb_select_model, F.data == "admin:select_model", is_admin
    )
    router.callback_query.register(
        cb_select_quality, F.data == "admin:select_quality", is_admin
    )
    router.callback_query.register(
        cb_select_provider, F.data == "admin:select_provider", is_admin
    )

    # Регистрация сохранений параметров
    router.callback_query.register(
        cb_save_model, F.data.startswith("admin:model:"), is_admin
    )
    router.callback_query.register(
        cb_save_quality, F.data.startswith("admin:quality:"), is_admin
    )
    router.callback_query.register(
        cb_save_provider, F.data.startswith("admin:provider:"), is_admin
    )
