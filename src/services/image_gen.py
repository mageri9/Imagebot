import asyncio
from loguru import logger

from src.core.config import get_settings
from src.providers.gen_api import GenAPIProvider
from src.providers.openai_compat import OpenAICompatProvider
from src.services.settings import get_active_model, get_image_params
from src.services.quota import increment_usage, log_generation

settings = get_settings()

# ── 1. Инициализация пула доступных провайдеров ─────────────────────────────
PROVIDER_POOL = []

if settings.GENAPI_API_KEY:
    PROVIDER_POOL.append(
        {
            "name": "genapi",
            "provider": GenAPIProvider(
                api_key=settings.GENAPI_API_KEY, base_url=settings.GENAPI_BASE_URL
            ),
            "supports_edits": True,  # Поддерживает генерацию по картинкам
        }
    )

if settings.PROVIDER_API_KEY:
    PROVIDER_POOL.append(
        {
            "name": "aitunnel",
            "provider": OpenAICompatProvider(
                api_key=settings.PROVIDER_API_KEY, base_url=settings.PROVIDER_BASE_URL
            ),
            "supports_edits": True,
        }
    )

# Если настройки пусты, создаем дефолтную заглушку, чтобы избежать падения
if not PROVIDER_POOL:
    PROVIDER_POOL.append(
        {
            "name": "aitunnel_fallback",
            "provider": OpenAICompatProvider(
                api_key=settings.PROVIDER_API_KEY or "empty_key",
                base_url=settings.PROVIDER_BASE_URL or "https://api.aitunnel.ru/v1",
            ),
            "supports_edits": False,
        }
    )

# Переменные состояния для Round Robin
_rr_index = 0
_lock = asyncio.Lock()


async def _get_next_provider(require_edits: bool = False) -> dict:
    """Выбирает провайдер с учетом принудительного выбора в БД, по кругу и поддержки функций."""
    global _rr_index

    # Ленивый импорт для предотвращения циклической зависимости
    from src.services.settings import get_setting

    forced_provider = await get_setting("provider_type", "auto")
    forced_provider = forced_provider.lower()

    # Фильтруем пул по поддержке генерации по изображениям, если это требуется
    available_pool = PROVIDER_POOL
    if require_edits:
        available_pool = [p for p in PROVIDER_POOL if p.get("supports_edits", True)]
        if not available_pool:
            raise NotImplementedError(
                "Нет доступных провайдеров с поддержкой генерации по фото."
            )

    async with _lock:
        # Если админ принудительно зафиксировал конкретного провайдера
        if forced_provider in ("genapi", "aitunnel", "openai_compat"):
            target_name = (
                "aitunnel" if forced_provider == "openai_compat" else forced_provider
            )
            # Проверяем, есть ли принудительный провайдер в нашем отфильтрованном пуле
            for prov in available_pool:
                if prov["name"] == target_name:
                    return prov

        # Иначе используем стандартную балансировку Round Robin по доступному пулу
        prov_config = available_pool[_rr_index % len(available_pool)]
        _rr_index += 1
        return prov_config


# ── 2. Умное сопоставление моделей (Smart Model Mapping) ──────────────────────
MODEL_MAPS = {
    "genapi": {
        "gpt-image": "flux-2",  # Посылаем в стабильный Flux-2 на GenAPI
        "flux": "flux-2",
        "midjourney": "midjourney",
        "sd3": "sd3",
    },
    "aitunnel": {
        "gpt-image": "gpt-image-2",  # Нативная GPT Image 2 в AITunnel (исправлено на gpt-image-2)
        "flux": "flux-pro",
        "midjourney": "seedream",
        "sd3": "seedream",
    },
}


def _resolve_model(provider_name: str, requested_model: str) -> str:
    """Преобразует абстрактную модель в точное имя для активного провайдера."""
    req_lower = requested_model.lower()
    mapping = MODEL_MAPS.get(provider_name, {})

    for key, target_name in mapping.items():
        if key in req_lower:
            return target_name

    return requested_model


# ── 3. Логика генерации (с Circuit Breaker и Свойствами провайдеров) ──────────


# Полное обновление функций генерации в src/services/image_gen.py


async def generate_from_text(user_id: int, prompt: str) -> bytes:
    requested_model = await get_active_model()
    params = await get_image_params()

    last_error = None

    for attempt in range(len(PROVIDER_POOL)):
        prov_config = await _get_next_provider(require_edits=False)
        prov_name = prov_config["name"]
        provider = prov_config["provider"]

        target_model = _resolve_model(prov_name, requested_model)

        logger.info(
            f"[text gen] Attempt {attempt + 1}/{len(PROVIDER_POOL)}: trying '{prov_name}' with model '{target_model}'"
        )

        try:
            result = await provider.generate(
                prompt=prompt,
                model=target_model,
                size=params["size"],
                quality=params["quality"],
            )
            await increment_usage(user_id)
            await log_generation(
                user_id, mode="text", model=target_model, prompt=prompt
            )
            return result

        except (ValueError, KeyError, TypeError) as e:
            # Ошибка локального разбора успешного ответа (деньги уже списались!)
            # Мгновенно блокируем fallback, чтобы не платить повторно на другом сервисе
            logger.critical(
                f"Parser error on SUCCESSFUL generation from '{prov_name}': {e}. Blocking fallback to prevent double-charging!"
            )
            raise RuntimeError(
                f"Изображение было успешно сгенерировано провайдером '{prov_name}', "
                f"но произошла внутренняя ошибка обработки ответа: {e}. Пожалуйста, сообщите администратору."
            ) from e

        except Exception as e:
            # Обычные сетевые или авторизационные ошибки (деньги не списаны) — делаем fallback
            logger.warning(
                f"Provider '{prov_name}' failed with model '{target_model}': {e}. Trying fallback..."
            )
            last_error = e
            await log_generation(
                user_id,
                mode="text",
                model=target_model,
                prompt=prompt,
                success=False,
                error_msg=f"[{prov_name}] {e}",
            )

    raise RuntimeError(
        f"Все доступные ИИ-серверы временно недоступны. Последняя ошибка: {last_error}"
    )


async def generate_from_images(
    user_id: int,
    images: list[bytes],
    prompt: str,
) -> bytes:
    requested_model = await get_active_model()
    params = await get_image_params()
    mode = "image" if len(images) == 1 else "multi"

    last_error = None

    try:
        edit_pool_len = len([p for p in PROVIDER_POOL if p.get("supports_edits", True)])
        if edit_pool_len == 0:
            raise NotImplementedError(
                "В пуле нет активных провайдеров с поддержкой генерации по фото."
            )

        for attempt in range(edit_pool_len):
            prov_config = await _get_next_provider(require_edits=True)
            prov_name = prov_config["name"]
            provider = prov_config["provider"]

            target_model = _resolve_model(prov_name, requested_model)

            logger.info(
                f"[image gen] Attempt {attempt + 1}/{edit_pool_len}: trying '{prov_name}' with model '{target_model}'"
            )

            try:
                result = await provider.edit(
                    images=images,
                    prompt=prompt,
                    model=target_model,
                    size=params["size"],
                    quality=params["quality"],
                )
                await increment_usage(user_id)
                await log_generation(
                    user_id, mode=mode, model=target_model, prompt=prompt
                )
                return result

            except (ValueError, KeyError, TypeError) as e:
                # Блокируем повторные списания при успешной генерации по фото
                logger.critical(
                    f"Parser error on SUCCESSFUL image edit from '{prov_name}': {e}. Blocking fallback to prevent double-charging!"
                )
                raise RuntimeError(
                    f"Изображение было успешно изменено провайдером '{prov_name}', "
                    f"но произошла внутренняя ошибка обработки ответа: {e}. Пожалуйста, сообщите администратору."
                ) from e

            except Exception as e:
                logger.warning(
                    f"Provider '{prov_name}' failed with model '{target_model}': {e}. Trying fallback..."
                )
                last_error = e
                await log_generation(
                    user_id,
                    mode=mode,
                    model=target_model,
                    prompt=prompt,
                    success=False,
                    error_msg=f"[{prov_name}] {e}",
                )
    except NotImplementedError as ne:
        logger.error(f"Image generation request aborted: {ne}")
        raise RuntimeError(
            "Генерация по фото временно отключена, так как у текущих провайдеров нет технической поддержки этой функции."
        )

    raise RuntimeError(
        f"Все доступные ИИ-серверы генерации по фото временно недоступны. Последняя ошибка: {last_error}"
    )
