from loguru import logger
from src.providers.registry import get_provider
from src.services.settings import get_active_model, get_image_params
from src.services.quota import increment_usage, log_generation


async def generate_from_text(
    user_id: int,
    prompt: str,
) -> bytes:
    provider = get_provider()
    model = await get_active_model()
    params = await get_image_params()

    try:
        result = await provider.generate(prompt=prompt, model=model, **params)
        await increment_usage(user_id)
        await log_generation(user_id, mode="text", model=model, prompt=prompt)
        return result
    except Exception as e:
        logger.error(f"generate_from_text failed: {e}")
        await log_generation(user_id, mode="text", model=model, prompt=prompt, success=False, error_msg=str(e))
        raise


async def generate_from_images(
    user_id: int,
    images: list[bytes],
    prompt: str,
) -> bytes:
    provider = get_provider()
    model = await get_active_model()
    params = await get_image_params()

    mode = "image" if len(images) == 1 else "multi"

    try:
        result = await provider.edit(images=images, prompt=prompt, model=model, **params)
        await increment_usage(user_id)
        await log_generation(user_id, mode=mode, model=model, prompt=prompt)
        return result
    except Exception as e:
        logger.error(f"generate_from_images failed: {e}")
        await log_generation(user_id, mode=mode, model=model, prompt=prompt, success=False, error_msg=str(e))
        raise
