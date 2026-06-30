import html
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from loguru import logger

from src.core.config import get_settings
from src.keyboards.gen import (
    mode_keyboard,
    multi_image_keyboard,
    cancel_keyboard,
    main_menu,
)
from src.services.image_gen import generate_from_text, generate_from_images
from src.services.quota import check_quota
from src.states.generate import GenerateForm

router = Router()


def _max_multi() -> int:
    return get_settings().MAX_MULTI_IMAGES


# ── Entry point ──────────────────────────────────────────────────────────────


async def cmd_generate(message: Message, state: FSMContext):
    allowed, used, limit = await check_quota(message.from_user.id)
    if not allowed:
        await message.answer(
            f"⚠️ Лимит на сегодня исчерпан ({used}/{limit}).\nПриходи завтра!"
        )
        return

    await state.set_state(GenerateForm.choosing_mode)
    await message.answer(
        f"🎨 Выбери режим генерации:\n<i>Использовано сегодня: {used}/{limit}</i>",
        reply_markup=mode_keyboard(max_multi=_max_multi()),
    )


# ── Mode selection ────────────────────────────────────────────────────────────


async def cb_mode_text(query: CallbackQuery, state: FSMContext):
    await query.answer()
    await state.set_state(GenerateForm.waiting_prompt)
    await query.message.edit_text(
        "✏️ Напиши промпт — опиши что хочешь сгенерировать:",
        reply_markup=cancel_keyboard(),
    )


async def cb_mode_image(query: CallbackQuery, state: FSMContext):
    await query.answer()
    await state.update_data(images=[], mode="image")
    await state.set_state(GenerateForm.waiting_image)
    sent_msg = await query.message.edit_text(
        "🖼 Отправь фото для редактирования:",
        reply_markup=cancel_keyboard(),
    )
    await state.update_data(last_msg_id=sent_msg.message_id)


async def cb_mode_multi(query: CallbackQuery, state: FSMContext):
    await query.answer()
    await state.update_data(images=[], mode="multi")
    await state.set_state(GenerateForm.waiting_image)
    max_multi = _max_multi()
    sent_msg = await query.message.edit_text(
        f"🖼🖼 Отправляй фото по одному (до {max_multi} штук).\n"
        f"Когда загрузишь все — нажми «Готово».\n\n"
        f"⚠️ <b>ВАЖНО:</b> Отправляйте фото строго ПО ОДНОМУ (не альбомом), делая паузу в 1-2 секунды! "
        f"Если отправить их альбомом, часть картинок может потеряться.",
        reply_markup=cancel_keyboard(),
    )
    await state.update_data(last_msg_id=sent_msg.message_id)


# ── Text prompt → generate ────────────────────────────────────────────────────


async def receive_prompt(message: Message, state: FSMContext):
    prompt = message.text.strip()
    await state.clear()

    wait_msg = await message.answer("⏳ Генерирую, подожди...")
    try:
        image_bytes = await generate_from_text(
            user_id=message.from_user.id,
            prompt=prompt,
        )
        await wait_msg.delete()
        await message.answer_photo(
            photo=BufferedInputFile(image_bytes, filename="result.png"),
            caption=f"🎨 <b>Промпт:</b> {html.escape(prompt)}",
            reply_markup=main_menu(),
        )
    except Exception as e:
        logger.error(f"Text generation error: {e}")
        await wait_msg.edit_text(
            f"❌ Ошибка генерации: <code>{html.escape(str(e))}</code>"
        )


# ── Image upload ──────────────────────────────────────────────────────────────


async def receive_image(message: Message, state: FSMContext, bot: Bot):
    if not message.photo:
        await message.answer("Нужно отправить фото, не файл.")
        return

    # Удаляем предыдущее статус-сообщение бота с кнопками "Отмена"
    data = await state.get_data()
    last_msg_id = data.get("last_msg_id")
    if last_msg_id:
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=last_msg_id)
        except Exception:
            pass

    # Сохраняем исключительно строковый file_id (безопасно для Redis JSON)
    file_id = message.photo[-1].file_id

    images: list[str] = data.get("images", [])
    images.append(file_id)

    logger.info(f"[multi] received image file_id={file_id}")

    mode = data.get("mode", "image")
    max_multi = _max_multi()

    if mode == "image":
        await state.update_data(images=images)
        await state.set_state(GenerateForm.waiting_image_prompt)
        sent_msg = await message.answer(
            "✅ Фото получено. Теперь напиши промпт — что сделать с изображением:",
            reply_markup=cancel_keyboard(),
        )
        await state.update_data(last_msg_id=sent_msg.message_id)
    else:
        await state.update_data(images=images)
        count = len(images)
        if count >= max_multi:
            await state.set_state(GenerateForm.waiting_image_prompt)
            sent_msg = await message.answer(
                f"✅ Загружено {count} фото (максимум). Напиши промпт:",
                reply_markup=cancel_keyboard(),
            )
            await state.update_data(last_msg_id=sent_msg.message_id)
        else:
            await state.set_state(GenerateForm.waiting_more_images)
            sent_msg = await message.answer(
                f"✅ Фото {count} загружено. Отправь ещё или нажми «Готово»:\n\n"
                f"⚠️ <i>Напоминание: отправляйте фото по одному, не альбомом!</i>",
                reply_markup=multi_image_keyboard(count=count, max_multi=max_multi),
            )
            await state.update_data(last_msg_id=sent_msg.message_id)


async def receive_more_image(message: Message, state: FSMContext, bot: Bot):
    """Additional images in multi mode."""
    await receive_image(message, state, bot)


async def cb_done_collecting(query: CallbackQuery, state: FSMContext):
    await query.answer()
    data = await state.get_data()
    count = len(data.get("images", []))

    logger.info(f"[multi] before generation images={count}")

    await state.set_state(GenerateForm.waiting_image_prompt)
    await query.message.edit_text(
        f"✅ Загружено {count} фото. Напиши промпт — что сделать с изображениями:",
        reply_markup=cancel_keyboard(),
    )


# ── Image prompt → generate ───────────────────────────────────────────────────


async def receive_image_prompt(message: Message, state: FSMContext, bot: Bot):
    prompt = message.text.strip()
    data = await state.get_data()

    # Удаляем Inline-сообщение с кнопкой отмены
    last_msg_id = data.get("last_msg_id")
    if last_msg_id:
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=last_msg_id)
        except Exception:
            pass

    # Извлекаем сохраненные file_id
    image_ids: list[str] = data.get("images", [])
    await state.clear()

    wait_msg = await message.answer("⏳ Генерирую, подожди...")
    try:
        # Скачиваем бинарные данные из Telegram непосредственно перед запросом в ИИ
        images_bytes = []
        for file_id in image_ids:
            file = await bot.get_file(file_id)
            buf = await bot.download_file(file.file_path)
            images_bytes.append(buf.read())

        image_bytes = await generate_from_images(
            user_id=message.from_user.id,
            images=images_bytes,
            prompt=prompt,
        )
        await wait_msg.delete()
        await message.answer_photo(
            photo=BufferedInputFile(image_bytes, filename="result.png"),
            caption=f"🎨 <b>Промпт:</b> {html.escape(prompt)}",
            reply_markup=main_menu(),
        )
    except Exception as e:
        logger.error(f"Image generation error: {e}")
        await wait_msg.edit_text(
            f"❌ Ошибка генерации: <code>{html.escape(str(e))}</code>"
        )


# ── Cancel ────────────────────────────────────────────────────────────────────


async def cb_cancel(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await query.answer()
    await query.message.edit_text("❌ Отменено.")


async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Отменено.", reply_markup=main_menu())


# ── Register ──────────────────────────────────────────────────────────────────


def register_handlers():
    router.message.register(cmd_generate, Command("generate", "gen", "g"))
    router.message.register(cmd_generate, F.text == "🎨 Сгенерировать")
    router.message.register(cmd_cancel, Command("cancel"), GenerateForm())

    router.callback_query.register(
        cb_mode_text, F.data == "mode:text", GenerateForm.choosing_mode
    )
    router.callback_query.register(
        cb_mode_image, F.data == "mode:image", GenerateForm.choosing_mode
    )
    router.callback_query.register(
        cb_mode_multi, F.data == "mode:multi", GenerateForm.choosing_mode
    )

    router.message.register(receive_prompt, GenerateForm.waiting_prompt, F.text)
    router.message.register(receive_image, GenerateForm.waiting_image, F.photo)
    router.message.register(
        receive_more_image, GenerateForm.waiting_more_images, F.photo
    )
    router.message.register(
        receive_image_prompt, GenerateForm.waiting_image_prompt, F.text
    )

    router.callback_query.register(
        cb_done_collecting, F.data == "gen:done", GenerateForm.waiting_more_images
    )
    router.callback_query.register(cb_cancel, F.data == "gen:cancel", GenerateForm())
