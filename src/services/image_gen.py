import asyncio
import json

from loguru import logger
import httpx

from src.core.config import get_settings
from src.core.redis import get_redis
from src.providers.gen_api import GenAPIProvider
from src.providers.openai_compat import OpenAICompatProvider
from src.services.settings import get_active_model, get_image_params
from src.services.quota import try_consume_quota, release_quota, log_generation


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
            "supports_edits": False,  # Gen-API не принимает файлы через API корректно
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

if not PROVIDER_POOL:
    raise RuntimeError(
        "Не настроен ни один провайдер генерации изображений. "
        "Заполни GENAPI_API_KEY (для Gen-API) или PROVIDER_API_KEY + PROVIDER_BASE_URL "
        "(для OpenAI-совместимого агрегатора) в .env и перезапусти бота."
    )

logger.info(
    f"Provider pool initialized: {[p['name'] for p in PROVIDER_POOL]}"
)

# Переменные состояния для Round Robin
_rr_index = 0
_lock = asyncio.Lock()


async def _get_next_provider(require_edits: bool = False, tried: set[str] | None = None) -> dict | None:
    """
    Выбирает провайдер с учетом принудительного выбора в БД, по кругу и поддержки функций.
    `tried` — имена провайдеров, уже опробованных в рамках текущего запроса на генерацию;
    они исключаются, чтобы «fallback» не долбил один и тот же упавший провайдер повторно.
    Возвращает None, если пробовать больше нечего.
    """
    global _rr_index
    tried = tried or set()

    # Ленивый импорт для предотвращения циклической зависимости
    from src.services.settings import get_setting

    forced_provider = await get_setting("provider_type", "auto")
    forced_provider = forced_provider.lower()

    # Фильтруем пул по поддержке генерации по изображениям, если это требуется
    available_pool = PROVIDER_POOL
    if require_edits:
        available_pool = [p for p in available_pool if p.get("supports_edits", True)]
        if not available_pool:
            raise NotImplementedError(
                "Нет доступных провайдеров с поддержкой генерации по фото."
            )

    # Исключаем уже опробованные в этом запросе провайдеры — это и есть настоящий fallback
    candidates = [p for p in available_pool if p["name"] not in tried]
    if not candidates:
        return None

    async with _lock:
        # Если админ принудительно зафиксировал конкретного провайдера
        if forced_provider in ("genapi", "aitunnel", "openai_compat"):
            target_name = (
                "aitunnel" if forced_provider == "openai_compat" else forced_provider
            )
            # Используем принудительный провайдер, пока он ещё не был опробован в этом запросе
            for prov in candidates:
                if prov["name"] == target_name:
                    return prov

        # Round Robin по оставшимся неопробованным провайдерам
        prov_config = candidates[_rr_index % len(candidates)]
        _rr_index += 1
        return prov_config


# ── 2. Умное сопоставление моделей (Smart Model Mapping) ──────────────────────
MODEL_MAPS = {
    "genapi": {
        "gpt-image-2": "gpt-image-2",  # точное совпадение — приоритет
        "gpt-image": "gpt-image-2",
        "flux": "flux-2",
        "midjourney": "midjourney",
        "sd3": "sd3"
    },
    "aitunnel": {
        "gpt-image-2": "gpt-image-2",  # точное совпадение — приоритет
        "gpt-image": "gpt-image-2",
        "flux": "flux-pro",
        "midjourney": "seedream",
        "sd3": "seedream"
    }
}


def _resolve_model(provider_name: str, requested_model: str) -> str:
    """Преобразует абстрактную модель в точное имя для активного провайдера."""
    req_lower = requested_model.strip().lower()
    mapping = MODEL_MAPS.get(provider_name, {})

    # Точное совпадение по ключу — самый предсказуемый путь
    if req_lower in mapping:
        return mapping[req_lower]

    # Фолбэк на подстроку только если точного совпадения нет
    # (на случай значений, оставшихся в DEFAULT_IMAGE_MODEL из .env, например "gpt-image-1")
    for key, target_name in mapping.items():
        if key in req_lower:
            logger.warning(
                f"[model resolve] '{requested_model}' matched by substring on key '{key}' "
                f"for provider '{provider_name}' — consider using exact model key."
            )
            return target_name

    logger.warning(
        f"[model resolve] No mapping found for '{requested_model}' on provider "
        f"'{provider_name}', passing through as-is."
    )
    return requested_model


# ── 3. Логика генерации (с Circuit Breaker и Свойствами провайдеров) ──────────

async def _publish_telemetry(
    project: str,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    modality: str,
) -> None:
    """Отправляет событие телеметрии в Redis Pub/Sub шину управляющего центра Nexus."""
    try:
        redis_client = get_redis()
        event_data = {
            "event_type": "ai.request",
            "payload": {
                "project": project,
                "provider": provider,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "modality": modality,
            },
        }
        await redis_client.publish(
            "nexus:pubsub:telemetry", json.dumps(event_data, ensure_ascii=False)
        )
        logger.info(
            f"[telemetry] Published to nexus:pubsub:telemetry | "
            f"{project} ({provider}:{model}:{modality}) -> {prompt_tokens}p/{completion_tokens}c"
        )
    except Exception as e:
        logger.error(f"[telemetry] Failed to publish telemetry event: {e}")


async def generate_from_text(user_id: int, prompt: str) -> bytes:
    allowed, used, limit = await try_consume_quota(user_id)
    if not allowed:
        raise RuntimeError(
            f"Лимит на сегодня исчерпан ({used}/{limit}). Приходи завтра!"
        )

    requested_model = await get_active_model()
    params = await get_image_params()

    last_error = None
    tried_providers: set[str] = set()

    for attempt in range(len(PROVIDER_POOL)):
        prov_config = await _get_next_provider(
            require_edits=False, tried=tried_providers
        )
        if prov_config is None:
            logger.info("[text gen] No untried providers left, stopping fallback loop")
            break
        prov_name = prov_config["name"]
        tried_providers.add(prov_name)
        provider = prov_config["provider"]

        target_model = _resolve_model(prov_name, requested_model)

        logger.info(
            f"[text gen] Attempt {attempt + 1}/{len(PROVIDER_POOL)}: trying '{prov_name}' with model '{target_model}'"
        )

        try:
            # Распаковываем кортеж (результат, токены)
            result, usage_data = await _call_with_retries(
                lambda: provider.generate(
                    prompt=prompt,
                    model=target_model,
                    size=params["size"],
                    quality=params["quality"],
                ),
                prov_name,
            )
            await log_generation(
                user_id, mode="text", model=target_model, prompt=prompt
            )

            # Публикация телеметрии (модальность: text)
            await _publish_telemetry(
                project="imagebot",
                provider=prov_name,
                model=target_model,
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                modality="text",
            )

            return result

        except (ValueError, KeyError, TypeError) as e:
            logger.critical(
                f"Parser error on SUCCESSFUL generation from '{prov_name}': {e}. Blocking fallback to prevent double-charging!"
            )
            raise RuntimeError(
                f"Изображение было успешно сгенерировано провайдером '{prov_name}', "
                f"но произошла внутренняя ошибка обработки ответа: {e}. Пожалуйста, сообщите администратору."
            ) from e

        except Exception as e:
            if _is_nsfw_error(e):
                logger.info(
                    f"[{prov_name}] NSFW/moderation rejection for user_id={user_id}"
                )
                await release_quota(user_id)
                raise NSFWContentError("Запрос отклонён фильтром модерации.") from e

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

    await release_quota(user_id)
    raise RuntimeError(
        f"Все доступные ИИ-серверы временно недоступны. Последняя ошибка: {last_error}"
    )


async def generate_from_images(
    user_id: int,
    images: list[bytes],
    prompt: str,
) -> bytes:
    allowed, used, limit = await try_consume_quota(user_id)
    if not allowed:
        raise RuntimeError(
            f"Лимит на сегодня исчерпан ({used}/{limit}). Приходи завтра!"
        )

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

        tried_providers: set[str] = set()

        for attempt in range(edit_pool_len):
            prov_config = await _get_next_provider(
                require_edits=True, tried=tried_providers
            )
            if prov_config is None:
                logger.info(
                    "[image gen] No untried providers left, stopping fallback loop"
                )
                break
            prov_name = prov_config["name"]
            tried_providers.add(prov_name)
            provider = prov_config["provider"]

            target_model = _resolve_model(prov_name, requested_model)

            logger.info(
                f"[image gen] Attempt {attempt + 1}/{edit_pool_len}: trying '{prov_name}' with model '{target_model}'"
            )

            try:
                # Распаковываем кортеж (результат, токены)
                result, usage_data = await _call_with_retries(
                    lambda: provider.edit(
                        images=images,
                        prompt=prompt,
                        model=target_model,
                        size=params["size"],
                        quality=params["quality"],
                    ),
                    prov_name,
                )
                await log_generation(
                    user_id, mode=mode, model=target_model, prompt=prompt
                )

                # Публикация телеметрии (модальность: vision)
                await _publish_telemetry(
                    project="imagebot",
                    provider=prov_name,
                    model=target_model,
                    prompt_tokens=usage_data.get("prompt_tokens", 0),
                    completion_tokens=usage_data.get("completion_tokens", 0),
                    modality="vision",
                )

                return result

            except (ValueError, KeyError, TypeError) as e:
                logger.critical(
                    f"Parser error on SUCCESSFUL image edit from '{prov_name}': {e}. Blocking fallback to prevent double-charging!"
                )
                raise RuntimeError(
                    f"Изображение было успешно изменено провайдером '{prov_name}', "
                    f"но произошла внутренняя ошибка обработки ответа: {e}. Пожалуйста, сообщите администратору."
                ) from e

            except Exception as e:
                if _is_nsfw_error(e):
                    logger.info(
                        f"[{prov_name}] NSFW/moderation rejection for user_id={user_id}"
                    )
                    await release_quota(user_id)
                    raise NSFWContentError("Запрос отклонён фильтром модерации.") from e

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
        await release_quota(user_id)
        raise RuntimeError(
            "Генерация по фото временно отключена, так как у текущих провайдеров нет технической поддержки этой функции."
        )

    await release_quota(user_id)
    raise RuntimeError(
        f"Все доступные ИИ-серверы генерации по фото временно недоступны. Последняя ошибка: {last_error}"
    )


RETRYABLE_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
)

MAX_RETRIES_PER_PROVIDER = 2
RETRY_BACKOFF_BASE = 1.5  # seconds

class NSFWContentError(RuntimeError):
    """Провайдер отклонил запрос как содержащий запрещённый/explicit контент."""
    pass

NSFW_ERROR_MARKERS = (
    "moderation_blocked",        # AITunnel/OpenAI — точный код
    "content_policy_violation",  # альтернативный код OpenAI
    "safety system",             # текст сообщения OpenAI
    "image_generation_user_error",  # type из OpenAI error object
)


def _is_nsfw_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in NSFW_ERROR_MARKERS)

def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, RETRYABLE_EXCEPTIONS):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status >= 500 or status == 429
    return False


def _retry_after_seconds(exc: Exception) -> float | None:
    """Извлекает Retry-After из ответа 429, если провайдер его прислал."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    if exc.response.status_code != 429:
        return None
    retry_after = exc.response.headers.get("Retry-After")
    if not retry_after:
        return None
    try:
        return float(retry_after)
    except ValueError:
        return None

async def _call_with_retries(coro_factory, prov_name: str):
    """
     Вызывает coro_factory() с повторными попытками при временных сетевых ошибках
    (таймауты, обрывы соединения, 5xx, 429). Не ретраит остальные 4xx (авторизация,
    невалидный запрос и т.д.). Для 429 уважает заголовок Retry-After, если он есть.
     """
    last_exc = None
    for attempt in range(MAX_RETRIES_PER_PROVIDER + 1):
        try:
            return await coro_factory()
        except Exception as e:
            last_exc = e
            if not _is_retryable(e) or attempt == MAX_RETRIES_PER_PROVIDER:
                raise
            wait = _retry_after_seconds(e) or RETRY_BACKOFF_BASE * (2 ** attempt)
            logger.warning(
                f"[{prov_name}] transient error (attempt {attempt + 1}/{MAX_RETRIES_PER_PROVIDER + 1}): "
                f"{e}. Retrying in {wait:.1f}s..."
            )
            await asyncio.sleep(wait)
    raise last_exc