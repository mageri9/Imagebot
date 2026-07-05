import asyncio
import base64
import io
from PIL import Image
import httpx
from loguru import logger

from src.services.image_utils import composite_images

class GenAPIProvider:
    """
    Native Gen-API provider (https://api.gen-api.ru).

    Flow:
      1. POST /api/v1/networks/{model}  → get request_id
      2. Poll GET /api/v1/request/get/{request_id} until status == "success"
      3. Download result image from response URL

    Docs: https://gen-api.ru/docs
    """

    DEFAULT_POLL_INTERVAL = 2.0  # starting interval between polls (seconds)
    DEFAULT_MAX_POLL_INTERVAL = 10.0  # cap for backoff growth
    DEFAULT_TIMEOUT = 120.0  # give up after N seconds
    GENERATE_PATH = "/api/v1/networks/{model}"
    STATUS_PATH = "/api/v1/request/get/{request_id}"


    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.gen-api.ru",
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        max_poll_interval: float = DEFAULT_MAX_POLL_INTERVAL,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._poll_interval = poll_interval
        self._max_poll_interval = max_poll_interval
        self._timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    # ── internal helpers ──────────────────────────────────────────────────────

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

    async def _submit_multipart(
        self,
        client: httpx.AsyncClient,
        model: str,
        data: dict,
        files: list,
    ) -> str:
        url = self._base_url + self.GENERATE_PATH.format(model=model)
        logger.debug(
            f"[genapi] submit multipart POST {url} fields={list(data.keys())} files={len(files)}"
        )

        # Убираем Content-Type из заголовков — при multipart httpx сам выставит с boundary
        headers = {
            k: v for k, v in self._headers.items() if k.lower() != "content-type"
        }

        resp = await client.post(url, data=data, files=files, headers=headers)
        resp.raise_for_status()
        result = resp.json()

        request_id = result.get("request_id") or result.get("id")
        if not request_id:
            raise RuntimeError(f"Gen-API did not return request_id: {result}")

        logger.debug(f"[genapi] submitted request_id={request_id}")
        return str(request_id)

    async def _poll(self, client: httpx.AsyncClient, request_id: str) -> dict:
        url = self._base_url + self.STATUS_PATH.format(request_id=request_id)
        elapsed = 0.0
        current_interval = self._poll_interval

        while elapsed < self._timeout:
            await asyncio.sleep(current_interval)
            elapsed += current_interval

            resp = await client.get(url, headers=self._headers)
            resp.raise_for_status()
            data = resp.json()

            status = data.get("status", "").lower()
            logger.debug(
                f"[genapi] poll request_id={request_id} status={status} "
                f"elapsed={elapsed:.0f}s next_interval={current_interval:.1f}s"
            )

            if status == "success":
                return data
            if status in ("error", "failed", "cancelled"):
                raise RuntimeError(
                    f"Gen-API generation failed: {data.get('error') or data}"
                )

            # Экспоненциальный рост интервала с потолком — реже опрашиваем долгие задачи
            current_interval = min(current_interval * 1.5, self._max_poll_interval)

        raise TimeoutError(
            f"Gen-API timed out after {self._timeout}s (request_id={request_id})"
        )

    @staticmethod
    async def _download_result(client: httpx.AsyncClient, result: dict) -> bytes:
        """Extract image bytes from completed result safely with deep parsing."""
        logger.debug(f"[genapi] parsing result structure: {result}")

        raw_data = None

        # Сначала проверяем нативный формат Gen-API "result" (массив ссылок)
        if "result" in result:
            output = result["result"]
            if isinstance(output, list) and len(output) > 0:
                raw_data = output[0]
            elif isinstance(output, str):
                raw_data = output

        # Проверяем "full_response"
        elif "full_response" in result:
            response = result["full_response"]
            if isinstance(response, list) and response:
                item = response[0]
                if isinstance(item, dict):
                    raw_data = item.get("url")
                elif isinstance(item, str):
                    raw_data = item

        # Резервные поля
        elif result.get("b64_json"):
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
            raise ValueError(f"Gen-API result has no recognizable image data: {result}")

        # Если это base64 строка (не начинается с http)
        if isinstance(raw_data, str) and not raw_data.startswith("http"):
            try:
                if "," in raw_data:
                    raw_data = raw_data.split(",", 1)[1]
                img_bytes = base64.b64decode(raw_data)
                logger.info(
                    f"[genapi] successfully resolved and decoded base64 image (bytes={len(img_bytes)})"
                )
                return img_bytes
            except Exception as e:
                raise ValueError(f"Failed to decode base64 from Gen-API: {e}")

        # Если это URL — скачиваем картинку
        url = raw_data
        logger.info(f"[genapi] resolved image url={url}")

        resp = await client.get(url)
        resp.raise_for_status()

        logger.info(f"[genapi] downloaded bytes={len(resp.content)}")
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
            "image_size": size,
            "quality": quality,
            "num_images": 1,
            "output_format": "png",
        }

        request_id = await self._submit(self._client, model, payload)
        result = await self._poll(self._client, request_id)
        return await self._download_result(self._client, result)

    async def edit(
        self,
        images: list[bytes],
        prompt: str,
        model: str,
        size: str,
        quality: str,
    ) -> bytes:
        logger.debug(
            f"[genapi] edit model={model} images={len(images)} size={size} quality={quality}"
        )

        # Gen-API не поддерживает JSON-массив файлов через multipart —
        # склеиваем фото в панораму и шлём одним файлом через multipart
        if len(images) == 1:
            img_bytes = images[0]
        else:
            logger.info(f"[genapi] stitching {len(images)} images for single upload")
            img_bytes = composite_images(images)

        logger.info(f"[genapi] sending image as multipart file")

        data = {
            "prompt": prompt,
            "image_size": size,
            "quality": quality,
            "num_images": "1",
            "output_format": "png",
        }

        files = [("image_urls", ("image.png", img_bytes, "image/png"))]

        request_id = await self._submit_multipart(self._client, model, data, files)
        result = await self._poll(self._client, request_id)
        return await self._download_result(self._client, result)
