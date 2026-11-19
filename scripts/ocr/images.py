"""Page images for the OCR models: column strips and stacked line crops."""

from __future__ import annotations

import base64
import io

from PIL import Image, ImageDraw, ImageFont

LINES_PER_IMAGE = 15
_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def jpeg_b64(img: Image.Image, quality: int = 90) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


def n_strips(img: Image.Image, per_square: int = 3) -> int:
    """How many strips a column image needs: about one per width-squared of height."""
    return max(1, round(img.height / max(img.width, 1) * per_square / 3))


def strips(img: Image.Image, n: int) -> list[Image.Image]:
    """Cut a column image into n horizontal strips at the emptiest rows.

    Models downscale large images; a strip keeps the accents legible.
    """
    g = img.convert("L")
    w, h = g.size
    px = g.load()
    step = max(1, w // 400)
    ink = [sum(1 for x in range(0, w, step) if px[x, y] < 128) for y in range(h)]
    cuts = [0]
    for i in range(1, n):
        target = h * i // n
        lo = max(cuts[-1] + 50, target - h // (4 * n))
        hi = min(h - 50, target + h // (4 * n))
        if hi <= lo:
            continue
        cuts.append(min(range(lo, hi), key=lambda y: sum(ink[max(0, y - 2): y + 3])))
    cuts.append(h)
    return [img.crop((0, a, w, b)) for a, b in zip(cuts, cuts[1:])]


def stack(img: Image.Image, crops: list[tuple[int, tuple[int, int, int, int]]]) -> Image.Image:
    """Line crops stacked into one image, each labelled "L n" in a left margin.

    Sending one stacked image instead of one image per line keeps the input
    tokens near those of the page itself.
    """
    pieces = []
    for li, (x0, y0, x1, y1) in crops:
        pad = max(8, (y1 - y0) // 3)
        pieces.append((li, img.crop((max(0, x0 - pad), max(0, y0 - pad),
                                     min(img.width, x1 + pad), min(img.height, y1 + pad)))
                       .convert("RGB")))
    margin, gap = 170, 14
    width = margin + max(p.width for _, p in pieces)
    height = sum(p.height for _, p in pieces) + gap * len(pieces)
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype(_FONT, 44)
    except OSError:
        font = ImageFont.load_default(size=44)
    y = 0
    for li, p in pieces:
        canvas.paste(p, (margin, y))
        draw.text((8, y + max(0, p.height // 2 - 24)), f"L {li}", fill=(200, 0, 0), font=font)
        draw.line((0, y + p.height + gap // 2, width, y + p.height + gap // 2),
                  fill=(180, 180, 180), width=2)
        y += p.height + gap
    return canvas


Crop = tuple[int, tuple[int, int, int, int]]  # line id, line box


def stacked_chunks(img: Image.Image, crops: list[Crop]) -> list[str]:
    """Stacked images (base64 JPEG) of at most LINES_PER_IMAGE lines each."""
    return [jpeg_b64(stack(img, crops[k:k + LINES_PER_IMAGE]), quality=92)
            for k in range(0, len(crops), LINES_PER_IMAGE)]
