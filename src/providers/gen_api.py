import asyncio
import base64
import io
from PIL import Image
import httpx
from loguru import logger


class GenAPIProvider:
    """
    Native Gen-API provider (https://api.gen-api.ru).

    Flow:
      1. POST /api/v1/request/{model}  → get request_id
      2. Poll GET /api/v1/request/{request_id} until status == "success"
      3. Download result image from response URL

    Docs: https://gen-api.ru/docs
    """

    DEFAULT_POLL_INTERVAL = 2.0   # seconds between polls
    DEFAULT_TIMEOUT = 120.0       # give up after N seconds
    GENERATE_PATH = "/api/v1/request/{model}"
    STATUS_PATH = "/api/v1/request/{request_id}"

    # Gen-API uses its own size tokens
    SIZE_MAP = {
        "1024x1024": "1:1",
        "1792x1024": "16:9",
        "1024x1792": "9:16",
        "512x512": "1:1",
    }

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.gen-api.ru",
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._poll_interval = poll_interval
        self._timeout = timeout

    # ── internal helpers ──────────────────────────────────────────────────────

    def _size_to_ratio(self, size: str) -> str:
        return self.SIZE_MAP.get(size, "1:1")

    async def _submit(
        self,
        client: httpx.AsyncClient,
        model: str,
        payload: dict,
    ) -> str:
        url = self._base_url + self.GENERATE_PATH.format(model=model)
        logger.debug(f"[genapi] submit POST {url} payload={payload}")

        resp = await client.post(url, json=payload, headers=self._headers)
        resp.raise_for_status()
        data = resp.json()

        request_id = data.get("request_id") or data.get("id")
        if not request_id:
            raise RuntimeError(f"Gen-API did not return request_id: {data}")

        logger.debug(f"[genapi] submitted request_id={request_id}")
        return str(request_id)

    async def _poll(self, client: httpx.AsyncClient, request_id: str) -> dict:
        url = self._base_url + self.STATUS_PATH.format(request_id=request_id)
        elapsed = 0.0

        while elapsed < self._timeout:
            await asyncio.sleep(self._poll_interval)
            elapsed += self._poll_interval

            resp = await client.get(url, headers=self._headers)
            resp.raise_for_status()
            data = resp.json()

            status = data.get("status", "").lower()
            logger.debug(f"[genapi] poll request_id={request_id} status={status} elapsed={elapsed:.0f}s")

            if status == "success":
                return data
            if status in ("error", "failed", "cancelled"):
                raise RuntimeError(f"Gen-API generation failed: {data.get('error') or data}")

        raise TimeoutError(f"Gen-API timed out after {self._timeout}s (request_id={request_id})")

    @staticmethod
    async def _download_result(client: httpx.AsyncClient, result: dict) -> bytes:
        """Extract image bytes from completed result safely."""
        logger.debug(f"[genapi] parsing result structure: {result}")

        # 1. Безопасное извлечение строкового значения (URL или Base64) из различных полей
        raw_data = None

        if result.get("b64_json"):
            raw_data = result.get("b64_json")
        elif result.get("image"):
            raw_data = result.get("image")
        elif result.get("url"):
            raw_data = result.get("url")
        elif "output" in result:
            output = result["output"]
            if isinstance(output, list) and len(output) > 0:
                raw_data = output[0]
            elif isinstance(output, str):
                raw_data = output
        elif "images" in result:
            images = result["images"]
            if isinstance(images, list) and len(images) > 0:
                raw_data = images[0]
            elif isinstance(images, str):
                raw_data = images

        if not raw_data:
            raise RuntimeError(
                f"Gen-API result has no recognizable image data: {result}"
            )

        # 2. Если это base64-строка (не начинается с http)
        if isinstance(raw_data, str) and not raw_data.startswith("http"):
            try:
                # Если строка содержит Data URI заголовок, убираем его
                if "," in raw_data:
                    raw_data = raw_data.split(",", 1)[1]
                return base64.b64decode(raw_data)
            except Exception as e:
                raise RuntimeError(f"Failed to decode base64 from Gen-API: {e}")

        # 3. Если это URL — скачиваем картинку по сети
        url = raw_data
        logger.debug(f"[genapi] downloading result from {url}")
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content

    @staticmethod
    def _to_b64(image_bytes: bytes) -> str:
        """PNG-encode image and return as base64 string."""
        with Image.open(io.BytesIO(image_bytes)) as img:
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode()

    # ── public API ────────────────────────────────────────────────────────────

    async def generate(
        self,
        prompt: str,
        model: str,
        size: str,
        quality: str,
    ) -> bytes:
        logger.debug(f"[genapi] generate model={model} size={size} quality={quality}")

        payload = {
            "prompt": prompt,
            "ratio": self._size_to_ratio(size),
            "quality": quality,
            "num_images": 1,
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            request_id = await self._submit(client, model, payload)
            result = await self._poll(client, request_id)
            return await self._download_result(client, result)

    async def edit(
        self,
        images: list[bytes],
        prompt: str,
        model: str,
        size: str,
        quality: str,
    ) -> bytes:
        logger.debug(f"[genapi] edit model={model} images={len(images)} size={size} quality={quality}")

        payload = {
            "prompt": prompt,
            "ratio": self._size_to_ratio(size),
            "quality": quality,
            "num_images": 1,
            "images": [self._to_b64(img) for img in images],
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            request_id = await self._submit(client, model, payload)
            result = await self._poll(client, request_id)
            return await self._download_result(client, result)
