from .base import ImageProvider
from .openai_compat import OpenAICompatProvider
from src.core.config import get_settings

_provider: ImageProvider | None = None


def init_provider() -> None:
    """Call once on startup."""
    global _provider
    settings = get_settings()
    _provider = OpenAICompatProvider(
        api_key=settings.PROVIDER_API_KEY,
        base_url=settings.PROVIDER_BASE_URL,
    )


def get_provider() -> ImageProvider:
    if _provider is None:
        raise RuntimeError("Provider not initialized. Call init_provider() first.")
    return _provider


def swap_provider(new_provider: ImageProvider) -> None:
    """Hot-swap provider without restart. Useful for future admin command."""
    global _provider
    _provider = new_provider
