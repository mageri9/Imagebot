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
    PROVIDER_POOL.append({
        "name": "genapi",
        "provider": GenAPIProvider(
            api_key=settings.GENAPI_API_KEY, 
            base_url=settings.GENAPI_BASE_URL
        )
    })

if settings.PROVIDER_API_KEY:
    PROVIDER_POOL.append({
        "name": "aitunnel",
        "provider": OpenAICompatProvider(
            api_key=settings.PROVIDER_API_KEY, 
            base_url=settings.PROVIDER_BASE_URL
        )
    })

# Если настройки пусты, создаем дефолтную заглушку, чтобы избежать падения
if not PROVIDER_POOL:
    PROVIDER_POOL.append({
        "name": "aitunnel_fallback",
        "provider": OpenAICompatProvider(
            api_key=settings.PROVIDER_API_KEY or "empty_key", 
            base_url=settings.PROVIDER_BASE_URL or "https://api.aitunnel.ru/v1"
        )
    })

# Переменные состояния для Round Robin
_rr_index = 0
_lock = asyncio.Lock()


async def _get_next_provider() -> dict:
    """Выбирает следующий провайдер из пула по кругу (Round Robin)."""
    global _rr_index
    async with _lock:
        prov_config = PROVIDER_POOL[_rr_index % len(PROVIDER_POOL)]
        _rr_index += 1
        return prov_config


# ── 2. Логика генерации (с Circuit Breaker) ──────────────────────────────────

async def generate_from_text(user_id: int, prompt: str) -> bytes:
    model = await get_active_model()
    params = await get_image_params()

    last_error = None

    # Пытаемся по очереди пройти по всем провайдерам в пуле (Circuit Breaker)
    for attempt in range(len(PROVIDER_POOL)):
        prov_config = await _get_next_provider()
        prov_name = prov_config["name"]
        provider = prov_config["provider"]

        logger.info(f"[text gen] Attempt {attempt+1}/{len(PROVIDER_POOL)}: trying '{prov_name}' with model '{model}'")

        try:
            result = await provider.generate(
                prompt=prompt,
                model=model,
                size=params["size"],
                quality=params["quality"],
            )
            # В случае успеха списываем попытку, пишем успешный лог и отдаем картинку
            await increment_usage(user_id)
            await log_generation(user_id, mode="text", model=model, prompt=prompt)
            return result
        except Exception as e:
            logger.warning(f"Provider '{prov_name}' failed with error: {e}. Trying fallback...")
            last_error = e
            # Логируем неудачу для этого провайдера в БД, но цикл продолжается
            await log_generation(
                user_id, mode="text", model=model, prompt=prompt,
                success=False, error_msg=f"[{prov_name}] {e}"
            )

    raise RuntimeError(f"Все доступные ИИ-серверы временно недоступны. Последняя ошибка: {last_error}")


async def generate_from_images(
    user_id: int,
    images: list[bytes],
    prompt: str,
) -> bytes:
    model = await get_active_model()
    params = await get_image_params()
    mode = "image" if len(images) == 1 else "multi"

    last_error = None

    for attempt in range(len(PROVIDER_POOL)):
        prov_config = await _get_next_provider()
        prov_name = prov_config["name"]
        provider = prov_config["provider"]

        logger.info(f"[image gen] Attempt {attempt+1}/{len(PROVIDER_POOL)}: trying '{prov_name}' with model '{model}'")

        try:
            result = await provider.edit(
                images=images,
                prompt=prompt,
                model=model,
                size=params["size"],
                quality=params["quality"],
            )
            await increment_usage(user_id)
            await log_generation(user_id, mode=mode, model=model, prompt=prompt)
            return result
        except Exception as e:
            logger.warning(f"Provider '{prov_name}' failed with error: {e}. Trying fallback...")
            last_error = e
            await log_generation(
                user_id, mode=mode, model=model, prompt=prompt,
                success=False, error_msg=f"[{prov_name}] {e}"
            )

    raise RuntimeError(f"Все доступные ИИ-серверы временно недоступны. Последняя ошибка: {last_error}")