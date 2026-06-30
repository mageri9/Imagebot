import io
import base64
from PIL import Image
from openai import AsyncOpenAI
from loguru import logger


def _to_png(image_bytes: bytes) -> bytes:
    """
    Convert any image to RGB PNG (no transparency).
    Required by images/edits endpoint.
    """
    with Image.open(io.BytesIO(image_bytes)) as img:
        if img.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
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
        Keeps all images at the same height (min height of all).
        """
        pil_images = []
        for raw in images:
            with Image.open(io.BytesIO(raw)) as img:
                pil_images.append(img.convert("RGB").copy())

        min_h = min(img.height for img in pil_images)
        resized = []
        for img in pil_images:
            ratio = min_h / img.height
            resized.append(img.resize((int(img.width * ratio), min_h), Image.LANCZOS))

        total_w = sum(img.width for img in resized)
        canvas = Image.new("RGB", (total_w, min_h), (255, 255, 255))
        x = 0
        for img in resized:
            canvas.paste(img, (x, 0))
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
        logger.debug(f"[openai_compat] edit model={model} images={len(images)} size={size} quality={quality}")

        if len(images) == 1:
            png = _to_png(images[0])
        else:
            # Composite into single image — works with all providers
            png = self._composite_images(images)

        image_file = ("image.png", io.BytesIO(png), "image/png")

        response = await self._client.images.edit(
            model=model,
            image=image_file,
            prompt=prompt,
            size=size,
            response_format="b64_json",
            n=1,
        )
        return base64.b64decode(response.data[0].b64_json)
