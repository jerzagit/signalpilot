"""
scripts/make_profile_pic.py
Generate a Telegram channel profile picture for SignalPilot (640x640 PNG).

Usage:
    python scripts/make_profile_pic.py [output.png]
"""

import logging
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("make_profile_pic")

SIZE = 640

# Brand palette (dark, trader-y)
BG_TOP = (10, 16, 32)
BG_BOTTOM = (16, 26, 54)
GRID = (255, 255, 255, 22)
TEXT_MAIN = (245, 248, 255)
TEXT_SUB = (120, 160, 220)
UP = (46, 204, 113)
DOWN = (235, 87, 87)
ACCENT = (64, 180, 255)


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        Path("C:/Windows/Fonts") / name,
        Path("C:/Windows/Fonts") / name.replace(".ttf", "-Bold.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _draw_chart(draw: ImageDraw.ImageDraw, cx: int) -> None:
    """Draw a mini candle chart with an ascending signal line and TP marker."""
    top, bottom = 92, 360
    xs = [cx - 190, cx - 130, cx - 70, cx - 10, cx + 50, cx + 110, cx + 170, cx + 215]
    opens = [300, 280, 300, 270, 290, 240, 265, 215]
    closes = [282, 302, 268, 292, 240, 268, 214, 235]
    colors = [DOWN, UP, DOWN, UP, UP, DOWN, UP, UP]
    body_w = 26
    wick_w = 3

    for x, o, c, color in zip(xs, opens, closes, colors):
        lo, hi = min(o, c), max(o, c)
        draw.line([(x, lo - 26), (x, hi + 26)], fill=color, width=wick_w)
        draw.rounded_rectangle(
            [x - body_w // 2, lo, x + body_w // 2, hi], radius=4, fill=color
        )

    # Ascending signal line over the highs.
    line = [
        (xs[0], 285),
        (xs[1], 262),
        (xs[2], 280),
        (xs[3], 238),
        (xs[4], 214),
        (xs[5], 200),
        (xs[6], 170),
    ]
    draw.line(line, fill=ACCENT, width=5, joint="curve")

    # TP target marker at the end of the line.
    tx, ty = xs[7], 128
    draw.ellipse([tx - 12, ty - 12, tx + 12, ty + 12], outline=UP, width=5)
    draw.ellipse([tx - 4, ty - 4, tx + 4, ty + 4], fill=UP)


def _draw_grid(draw: ImageDraw.ImageDraw) -> None:
    for y in range(80, 400, 40):
        draw.line([(40, y), (SIZE - 40, y)], fill=GRID, width=1)
    for x in range(80, SIZE - 40, 40):
        draw.line([(x, 80), (x, 400)], fill=GRID, width=1)


def make(output: str) -> Path:
    img = Image.new("RGB", (SIZE, SIZE))
    draw = ImageDraw.Draw(img)

    for y in range(SIZE):
        t = y / (SIZE - 1)
        color = tuple(
            round(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)
        )
        draw.line([(0, y), (SIZE, y)], fill=color)

    cx = SIZE // 2
    _draw_grid(draw)
    _draw_chart(draw, cx)

    main_font = _font("arialbd.ttf", 66)
    sub_font = _font("arial.ttf", 26)

    word = "SIGNALPILOT"
    label = "AUTOMATED SIGNALS · XAUUSD"

    left, _, right, _ = draw.textbbox((0, 0), word, font=main_font)
    w_main = right - left
    draw.text((cx - w_main / 2, 420), word, font=main_font, fill=TEXT_MAIN)

    left, _, right, _ = draw.textbbox((0, 0), label, font=sub_font)
    w_sub = right - left
    draw.text((cx - w_sub / 2, 512), label, font=sub_font, fill=TEXT_SUB)

    # Subtle vignette so it reads well on light chat themes.
    vignette = Image.new("L", (SIZE, SIZE), 0)
    vd = ImageDraw.Draw(vignette)
    vd.ellipse([-40, -40, SIZE + 40, SIZE + 40], fill=255)
    vignette = vignette.filter(ImageFilter.GaussianBlur(90))
    black = Image.new("RGB", (SIZE, SIZE), (8, 10, 20))
    img = Image.composite(img, black, vignette)

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    log.info("Profile picture written: %s (%dx%d)", out, *img.size)
    return out


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "assets/signalpilot_profile.png"
    make(target)