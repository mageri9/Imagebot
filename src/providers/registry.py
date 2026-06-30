from .base import ImageProvider
from src.core.config import get_settings

_provider: ImageProvider | None = None


def init_provider() -> None:
    """Call once on startup. Reads PROVIDER_TYPE from config."""
    global _provider
    settings = get_settings()

    ptype = settings.PROVIDER_TYPE.lower()

    if ptype == "genapi":
        from .gen_api import GenAPIProvider
        _provider = GenAPIProvider(
            api_key=settings.GENAPI_API_KEY,
            base_url=settings.GENAPI_BASE_URL,
        )
    else:
        # Default: any OpenAI-compatible aggregator
        from .openai_compat import OpenAICompatProvider
        _provider = OpenAICompatProvider(
            api_key=settings.PROVIDER_API_KEY,
            base_url=settings.PROVIDER_BASE_URL,
        )

    import logging
    logging.getLogger(__name__)  # loguru not available at module level
    from loguru import logger
    logger.info(f"Provider initialized: {ptype}")


def get_provider() -> ImageProvider:
    if _provider is None:
        raise RuntimeError("Provider not initialized. Call init_provider() first.")
    return _provider


def swap_provider(new_provider: ImageProvider) -> None:
    """Hot-swap provider without restart (future admin command)."""
    global _provider
    _provider = new_provider
