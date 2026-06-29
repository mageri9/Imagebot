from typing import Protocol, runtime_checkable


@runtime_checkable
class ImageProvider(Protocol):
    """
    Abstract interface for image generation providers.
    Any OpenAI-compatible API (ProxyAPI, OpenRouter, direct OpenAI, etc.)
    can be wrapped by implementing this protocol.
    """

    async def generate(
        self,
        prompt: str,
        model: str,
        size: str = "1024x1024",
        quality: str = "medium",
    ) -> bytes:
        """Text → image."""
        ...

    async def edit(
        self,
        images: list[bytes],
        prompt: str,
        model: str,
        size: str = "1024x1024",
        quality: str = "medium",
    ) -> bytes:
        """Image(s) + prompt → image. Handles both single and multi-image edits."""
        ...
