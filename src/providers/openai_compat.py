import io
import base64
from PIL import Image
from openai import AsyncOpenAI
from loguru import logger


def _to_png(image_bytes: bytes) -> bytes:
    """
    Convert any image to RGBA PNG (preserving transparency).
    Required by OpenAI images/edits endpoint to act as a mask.
    """
    with Image.open(io.BytesIO(image_bytes)) as img:
        # Принудительно используем RGBA, чтобы сохранить прозрачные пиксели
        if img.mode != "RGBA":
            img = img.convert("RGBA")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


class OpenAICompatProvider:
    """
    Works with any OpenAI-compatible aggregator:
      - ProxyAPI  (https://api.proxyapi.ru/openai/v1)
      - OpenRouter
      - Direct OpenAI

    No default values for size/quality — always supplied by caller
    so the source of truth stays in DB/config, not here.

    Multi-image edit note:
      Most OpenAI-compatible providers (including ProxyAPI) support only a
      single image in images/edits. When multiple images are provided we
      composite them into one canvas before sending, which is safe and gives
      the model full context. If your specific provider supports native
      multi-image, override _prepare_edit_image() in a subclass.
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
                # Сохраняем режим RGBA для каждого исходного фото
                pil_images.append(img.convert("RGBA").copy())

        min_h = min(img.height for img in pil_images)
        resized = []
        for img in pil_images:
            ratio = min_h / img.height
            resized.append(img.resize((int(img.width * ratio), min_h), Image.LANCZOS))

        total_w = sum(img.width for img in resized)

        # Создаем пустой абсолютно прозрачный холст (RGBA с прозрачностью 0)
        canvas = Image.new("RGBA", (total_w, min_h), (0, 0, 0, 0))
        x = 0
        for img in resized:
            # Накладываем изображение, используя его же альфа-канал в качестве маски
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
        logger.debug(f"[openai_compat] generate model={model} size={size} quality={quality}")
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

        # Не передаем response_format, так как AITunnel не поддерживает его в edits
        response = await self._client.images.edit(
            model=model,
            image=image_file,
            prompt=prompt,
            size=size,
            n=1,
        )

        # Скачиваем полученный результат по прямой ссылке
        url = response.data[0].url
        logger.info(f"[openai_compat] resolved edit url: {url}")

        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
