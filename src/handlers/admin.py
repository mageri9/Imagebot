import html
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.filters.check_admin import IsAdmin
from src.services.user import add_user, remove_user, list_users, set_user_limit
from src.services.settings import get_active_model, set_setting, get_image_params
from src.services.quota import get_usage, get_limit

router = Router()


async def cmd_admin(message: Message):
    await message.answer(
        "👑 <b>Админ-панель</b>\n\n"
        "/adduser &lt;user_id&gt; [&lt;limit&gt;] — добавить пользователя\n"
        "/removeuser &lt;user_id&gt; — убрать пользователя\n"
        "/users — список пользователей\n"
        "/setlimit &lt;user_id&gt; &lt;limit&gt; — изменить лимит\n"
        "/setmodel &lt;model&gt; — сменить модель\n"
        "/setquality &lt;low|medium|high&gt; — качество\n"
        "/setprovider &lt;genapi|aitunnel|auto&gt; — выбрать ИИ\n"
        "/stats — статистика\n"
        "/model — текущая модель"
    )


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
        await message.answer(f"ℹ️ Пользователь {user_id} уже существует (переактивирован).")


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


async def cmd_users(message: Message):
    users = await list_users()
    if not users:
        await message.answer("Нет активных пользователей.")
        return

    lines = ["👥 <b>Активные пользователи:</b>\n"]
    for u in users:
        used = await get_usage(u["user_id"])
        name = html.escape(u["full_name"] or "—")
        username = f"@{u['username']}" if u["username"] else "—"
        lines.append(
            f"• <code>{u['user_id']}</code> {name} ({username})\n"
            f"  Лимит: {used}/{u['daily_limit']} сегодня"
        )

    await message.answer("\n".join(lines))


async def cmd_set_model(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        current = await get_active_model()
        await message.answer(f"Текущая модель: <code>{current}</code>\n\nИспользование: /setmodel &lt;model&gt;")
        return

    model = parts[1].strip()
    await set_setting("image_model", model)
    await message.answer(f"✅ Модель изменена на <code>{model}</code>")


async def cmd_set_quality(message: Message):
    parts = message.text.split()
    if len(parts) < 2 or parts[1] not in ("low", "medium", "high"):
        await message.answer("Использование: /setquality &lt;low|medium|high&gt;")
        return

    quality = parts[1]
    await set_setting("image_quality", quality)
    await message.answer(f"✅ Качество установлено: <code>{quality}</code>")


async def cmd_model(message: Message):
    model = await get_active_model()
    params = await get_image_params()
    await message.answer(
        f"🤖 <b>Текущие настройки:</b>\n"
        f"Модель: <code>{model}</code>\n"
        f"Размер: <code>{params['size']}</code>\n"
        f"Качество: <code>{params['quality']}</code>"
    )

async def cmd_set_provider(message: Message):
    parts = message.text.split()
    if len(parts) < 2 or parts[1].lower() not in ("genapi", "aitunnel", "openai_compat", "auto"):
        await message.answer("Использование: /setprovider &lt;genapi|aitunnel|auto&gt;")
        return

    ptype = parts[1].lower()
    if ptype == "openai_compat":
        ptype = "aitunnel"

    await set_setting("provider_type", ptype)
    await message.answer(f"✅ Предпочтительный провайдер установлен: <code>{ptype}</code>")


def register_handlers():
    is_admin = IsAdmin()

    router.message.register(cmd_admin, Command("admin"), is_admin)
    router.message.register(cmd_add_user, Command("adduser"), is_admin)
    router.message.register(cmd_remove_user, Command("removeuser"), is_admin)
    router.message.register(cmd_set_limit, Command("setlimit"), is_admin)
    router.message.register(cmd_users, Command("users"), is_admin)
    router.message.register(cmd_set_model, Command("setmodel"), is_admin)
    router.message.register(cmd_set_quality, Command("setquality"), is_admin)
    router.message.register(cmd_model, Command("model"), is_admin)
    router.message.register(cmd_set_provider, Command("setprovider"), is_admin)
