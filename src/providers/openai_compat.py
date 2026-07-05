import io
import base64
from PIL import Image
from openai import AsyncOpenAI
import httpx
from loguru import logger

from src.services.image_utils import composite_images


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
        self._http_client = httpx.AsyncClient()

    async def close(self) -> None:
        await self._http_client.aclose()


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

        response = await self._client.images.generate(
            model=model,
            prompt=prompt,
            size=size,
            quality=quality,
            n=1,
        )

        img_item = response.data[0]

        # 1. Если ИИ-сервер вернул Base64 (AITunnel по умолчанию)
        if getattr(img_item, "b64_json", None):
            img_bytes = base64.b64decode(img_item.b64_json)
            logger.info(
                f"[openai_compat] resolved base64 image (bytes={len(img_bytes)})"
            )
            return img_bytes

        # 2. Если ИИ-сервер вернул прямую ссылку (OpenAI / ProxyAPI)
        elif getattr(img_item, "url", None):
            url = img_item.url
            logger.info(f"[openai_compat] resolved generate url: {url}")
            resp = await self._http_client.get(url)
            resp.raise_for_status()
            return resp.content
        else:
            raise ValueError(f"No image data returned from provider: {img_item}")

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

        # Диагностический лог отправки
        logger.info(f"[openai_compat] sending {len(images)} images to edits endpoint")

        if len(images) == 1:
            png = _to_png(images[0])
        else:
            png = composite_images(images)

        image_file = ("image.png", io.BytesIO(png), "image/png")

        response = await self._client.images.edit(
            model=model,
            image=image_file,
            prompt=prompt,
            size=size,
            quality=quality,
            n=1,
        )

        img_item = response.data[0]

        # 1. Если ИИ-сервер вернул Base64
        if getattr(img_item, "b64_json", None):
            img_bytes = base64.b64decode(img_item.b64_json)
            logger.info(
                f"[openai_compat] resolved base64 edit image (bytes={len(img_bytes)})"
            )
            return img_bytes

        # 2. Если ИИ-сервер вернул прямую ссылку

        elif getattr(img_item, "url", None):
            url = img_item.url
            logger.info(f"[openai_compat] resolved edit url: {url}")
            resp = await self._http_client.get(url)
            resp.raise_for_status()
            return resp.content
        else:
            raise ValueError(f"No image data returned from provider: {img_item}")
