import io
import base64
from PIL import Image
from openai import AsyncOpenAI
from loguru import logger


def _to_png(image_bytes: bytes) -> bytes:
    """
    Convert any image format to PNG without transparency.
    Required by OpenAI images/edits endpoint.
    """
    with Image.open(io.BytesIO(image_bytes)) as img:
        if img.mode in ("RGBA", "LA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


class OpenAICompatProvider:
    """
    Works with any OpenAI-compatible aggregator:
    - ProxyAPI (https://api.proxyapi.ru/openai/v1)
    - OpenRouter
    - Direct OpenAI
    - etc.

    To switch provider: just pass a different base_url + api_key.
    """

    def __init__(self, api_key: str, base_url: str):
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )

    async def generate(
        self,
        prompt: str,
        model: str,
        size: str = "1024x1024",
        quality: str = "medium",
    ) -> bytes:
        logger.debug(f"generate: model={model} size={size} quality={quality}")

        response = await self._client.images.generate(
            model=model,
            prompt=prompt,
            size=size,
            quality=quality,
            response_format="b64_json",
            n=1,
        )
        return base64.b64decode(response.data[0].b64_json)

    async def edit(
        self,
        images: list[bytes],
        prompt: str,
        model: str,
        size: str = "1024x1024",
        quality: str = "medium",
    ) -> bytes:
        logger.debug(f"edit: model={model} images={len(images)} size={size} quality={quality}")

        # Convert all images to PNG (API requirement)
        png_images = [_to_png(img) for img in images]

        # Build file tuples for multipart upload
        image_files = [
            ("image[]", (f"image_{i}.png", io.BytesIO(png), "image/png"))
            for i, png in enumerate(png_images)
        ]

        response = await self._client.images.edit(
            model=model,
            image=image_files if len(image_files) > 1 else image_files[0][1],
            prompt=prompt,
            size=size,
            response_format="b64_json",
            n=1,
        )
        return base64.b64decode(response.data[0].b64_json)
