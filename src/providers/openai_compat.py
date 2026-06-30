import io
from PIL import Image
from openai import AsyncOpenAI
import httpx
from loguru import logger


def _to_png(image_bytes: bytes) -> bytes:
    """
    Convert any image to RGBA PNG (preserving transparency).
    Required by OpenAI images/edits endpoint to act as a mask.
    """
    with Image.open(io.BytesIO(image_bytes)) as img:
        if img.mode != "RGBA":
            img = img.convert("RGBA")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


class OpenAICompatProvider:
    """
    Works with any OpenAI-compatible aggregator:
      - ProxyAPI (https://api.proxyapi.ru/openai/v1)
      - OpenRouter
      - Direct OpenAI
      - AITunnel (https://api.aitunnel.ru/v1)
    """

    def __init__(self, api_key: str, base_url: str):
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    # ── internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _composite_images(images: list[bytes]) -> bytes:
        """
        Stitch multiple images into a horizontal strip.
        Keeps all images at the same height (min height of all) and preserves transparency.
        """
        pil_images = []
        for raw in images:
            with Image.open(io.BytesIO(raw)) as img:
                pil_images.append(img.convert("RGBA").copy())

        min_h = min(img.height for img in pil_images)
        resized = []
        for img in pil_images:
            ratio = min_h / img.height
            resized.append(img.resize((int(img.width * ratio), min_h), Image.LANCZOS))

        total_w = sum(img.width for img in resized)

        canvas = Image.new("RGBA", (total_w, min_h), (0, 0, 0, 0))
        x = 0
        for img in resized:
            canvas.paste(img, (x, 0), img)
            x += img.width

        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        return buf.getvalue()

    # ── public API ────────────────────────────────────────────────────────────

    async def generate(
        self,
        prompt: str,
        model: str,
        size: str,
        quality: str,
    ) -> bytes:
        logger.debug(
            f"[openai_compat] generate model={model} size={size} quality={quality}"
        )

        # Не передаем response_format="b64_json", так как AITunnel его не поддерживает
        response = await self._client.images.generate(
            model=model,
            prompt=prompt,
            size=size,
            quality=quality,
            n=1,
        )

        # Извлекаем прямую ссылку на сгенерированный результат
        url = response.data[0].url
        logger.info(f"[openai_compat] resolved generate url: {url}")

        # Скачиваем бинарные данные картинки по сети
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content

    async def edit(
        self,
        images: list[bytes],
        prompt: str,
        model: str,
        size: str,
        quality: str,
    ) -> bytes:
        logger.debug(
            f"[openai_compat] edit model={model} images={len(images)} size={size} quality={quality}"
        )

        if len(images) == 1:
            png = _to_png(images[0])
        else:
            png = self._composite_images(images)

        image_file = ("image.png", io.BytesIO(png), "image/png")

        # Не передаем response_format, так как AITunnel его не поддерживает
        response = await self._client.images.edit(
            model=model,
            image=image_file,
            prompt=prompt,
            size=size,
            n=1,
        )

        # Извлекаем прямую ссылку на сгенерированный результат
        url = response.data[0].url
        logger.info(f"[openai_compat] resolved edit url: {url}")

        # Скачиваем бинарные данные картинки по сети
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
