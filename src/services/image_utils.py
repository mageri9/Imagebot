import io
from PIL import Image


def composite_images(images: list[bytes]) -> bytes:
    """
    Stitch multiple images into a horizontal strip.
    Keeps all images at the same height (min height of all) and preserves transparency.

    Used as a workaround for providers/aggregators that only accept a single
    image file per edit request, even when multiple source images are supplied
    by the user (multi-image generation mode).
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