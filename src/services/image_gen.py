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
        }
    )

if settings.PROVIDER_API_KEY:
    PROVIDER_POOL.append(
        {
            "name": "aitunnel",
            "provider": OpenAICompatProvider(
                api_key=settings.PROVIDER_API_KEY, base_url=settings.PROVIDER_BASE_URL
            ),
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
        }
    )

# Переменные состояния для Round Robin
_rr_index = 0
_lock = asyncio.Lock()


async def _get_next_provider() -> dict:
    """Выбирает провайдер с учетом принудительного выбора в БД или по кругу (Round Robin)."""
    global _rr_index

    # Ленивый импорт для предотвращения циклической зависимости
    from src.services.settings import get_setting

    forced_provider = await get_setting("provider_type", "auto")
    forced_provider = forced_provider.lower()

    async with _lock:
        # Если админ принудительно зафиксировал конкретного провайдера
        if forced_provider in ("genapi", "aitunnel", "openai_compat"):
            target_name = (
                "aitunnel" if forced_provider == "openai_compat" else forced_provider
            )
            # Ищем его среди инициализированных (настроенных в .env) провайдеров в пуле
            for prov in PROVIDER_POOL:
                if prov["name"] == target_name:
                    return prov

        # Иначе используем стандартную балансировку Round Robin
        prov_config = PROVIDER_POOL[_rr_index % len(PROVIDER_POOL)]
        _rr_index += 1
        return prov_config


# ── 2. Умное сопоставление моделей (Smart Model Mapping) ──────────────────────
# Сопоставляет пользовательский выбор из БД с точными названиями моделей на стороне ИИ
MODEL_MAPS = {
    "genapi": {
        "gpt-image": "flux-2",  # У GenAPI нет gpt-image, пускаем через качественный Flux-2
        "flux": "flux-2",
        "midjourney": "midjourney",
        "sd3": "sd3",
    },
    "aitunnel": {
        "gpt-image": "gpt-image",  # Нативная GPT Image 2 в AITunnel
        "flux": "flux-pro",  # Нативная Flux Pro в AITunnel
        "midjourney": "seedream",  # Сверхреалистичная модель Seedream 5.0 в AITunnel
        "sd3": "seedream",
    },
}


def _resolve_model(provider_name: str, requested_model: str) -> str:
    """Преобразует абстрактную модель в точное имя для активного провайдера."""
    req_lower = requested_model.lower()
    mapping = MODEL_MAPS.get(provider_name, {})

    # Ищем частичное совпадение ключевого слова в названии
    for key, target_name in mapping.items():
        if key in req_lower:
            return target_name

    # Если совпадений в таблице нет, передаем оригинальное имя
    return requested_model


# ── 3. Логика генерации (с Circuit Breaker и Smart Mapping) ──────────────────


async def generate_from_text(user_id: int, prompt: str) -> bytes:
    requested_model = await get_active_model()
    params = await get_image_params()

    last_error = None

    # Пытаемся по очереди пройти по всем провайдерам в пуле (Circuit Breaker)
    for attempt in range(len(PROVIDER_POOL)):
        prov_config = await _get_next_provider()
        prov_name = prov_config["name"]
        provider = prov_config["provider"]

        # Определяем точное имя модели под конкретного провайдера
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
        except Exception as e:
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

    for attempt in range(len(PROVIDER_POOL)):
        prov_config = await _get_next_provider()
        prov_name = prov_config["name"]
        provider = prov_config["provider"]

        # Определяем точное имя модели под конкретного провайдера
        target_model = _resolve_model(prov_name, requested_model)

        logger.info(
            f"[image gen] Attempt {attempt + 1}/{len(PROVIDER_POOL)}: trying '{prov_name}' with model '{target_model}'"
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
            await log_generation(user_id, mode=mode, model=target_model, prompt=prompt)
            return result
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

    raise RuntimeError(
        f"Все доступные ИИ-серверы временно недоступны. Последняя ошибка: {last_error}"
    )
