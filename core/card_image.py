"""
core/card_image.py
Render signal cards as branded PNG images so the feed is hard to copy/scrape
(text becomes a screenshot). Uses Pillow with the SignalPilot brand palette.

Every published card also carries a faint diagonal watermark so reposts can be
traced back to the @signalpilotv1 feed.
"""

import logging
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from core.signal import Signal

log = logging.getLogger(__name__)

UP = (46, 204, 113)
DOWN = (235, 87, 87)
TEXT_MAIN = (245, 248, 255)
TEXT_SUB = (120, 160, 220)
ACCENT = (64, 180, 255)
GOLD = (240, 196, 84)
BG_TOP = (10, 16, 32)
BG_BOTTOM = (16, 26, 54)
PILL_BG = (22, 34, 62)

WIDTH = 900
PAD = 44
_FONT_DIR = "C:/Windows/Fonts"
_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    key = (name, size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    for fname in (name, name.replace(".ttf", "-Bold.ttf")):
        path = Path(_FONT_DIR) / fname
        if path.exists():
            font = ImageFont.truetype(str(path), size)
            _FONT_CACHE[key] = font
            return font
    _FONT_CACHE[key] = ImageFont.load_default()
    return _FONT_CACHE[key]


def _vertical_gradient(size: tuple[int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / (h - 1)
        color = tuple(round(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (w, y)], fill=color)
    return img


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines, line = [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _pill(draw: ImageDraw.ImageDraw, cx: int, y: int, label: str, color: tuple[int, int, int]) -> None:
    font = _font("arialbd.ttf", 36)
    w = draw.textlength(label, font=font) + 56
    draw.rounded_rectangle(
        [cx - w / 2, y, cx + w / 2, y + 62], radius=31, fill=PILL_BG, outline=color, width=3
    )
    draw.text((cx, y + 32), label, font=font, fill=color, anchor="mm")


def _price_row(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y: int,
    label: str,
    value: str,
    value_color: tuple[int, int, int],
) -> None:
    draw.text((x0, y + 16), label, font=_font("arial.ttf", 30), fill=TEXT_SUB, anchor="lm")
    draw.text(
        (WIDTH - PAD, y + 16),
        value,
        font=_font("consola.ttf", 42),
        fill=value_color,
        anchor="rm",
    )


def _tp_box(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y: int,
    w: int,
    h: int,
    label: str,
    price: str,
    reached: bool,
) -> None:
    edge = UP if reached else ACCENT
    draw.rounded_rectangle([x0, y, x0 + w, y + h], radius=14, fill=PILL_BG, outline=edge, width=2)
    draw.text((x0 + w / 2, y + 22), label, font=_font("arialbd.ttf", 28), fill=TEXT_SUB, anchor="mm")
    draw.text(
        (x0 + w / 2, y + h - 26),
        price,
        font=_font("consola.ttf", 36),
        fill=TEXT_MAIN if reached else GOLD,
        anchor="mm",
    )


def render_signal_card(
    signal: Signal,
    news_context: list[str] | None = None,
    output_dir: str = "data/cards",
) -> Path:
    """Render a signal card to PNG and return its path."""
    direction = (signal.direction or "").lower()
    color = UP if direction == "buy" else DOWN
    glyph = "▲" if direction == "buy" else "▼"

    rows = 2  # entry + SL
    news_count = len(news_context) if news_context else 0
    tp_h = 118
    news_h = 84 * news_count + 40
    H = 300 + rows * 74 + tp_h + 92 + news_h + 70

    img = _vertical_gradient((WIDTH, H))
    draw = ImageDraw.Draw(img)

    brand_font = _font("arialbd.ttf", 40)
    brand = "SIGNALPILOT"
    draw.text((PAD, 36), brand, font=brand_font, fill=TEXT_MAIN, anchor="lm")
    draw.text(
        (WIDTH - PAD, 36),
        "AUTOMATED FEED",
        font=_font("arial.ttf", 26),
        fill=TEXT_SUB,
        anchor="rm",
    )

    y = 130
    _pill(draw, WIDTH // 2, y, f"{glyph} {signal.direction.upper()}", color)
    y += 96

    pair_font = _font("arialbd.ttf", 84)
    pair = signal.symbol.upper()
    w = draw.textlength(pair, font=pair_font)
    draw.text((WIDTH // 2 - w / 2, y), pair, font=pair_font, fill=TEXT_MAIN)
    draw.text(
        (WIDTH // 2, y + 66),
        f"GOLD / US DOLLAR" if "XAU" in pair else "FOREX · MAJOR",
        font=_font("arial.ttf", 26),
        fill=TEXT_SUB,
        anchor="mm",
    )
    y += 148

    draw.line([(PAD, y), (WIDTH - PAD, y)], fill=(45, 60, 100), width=2)
    y += 26

    _price_row(draw, PAD, y, "Entry", f"{signal.entry_low:g}", GOLD)
    y += 74
    _price_row(draw, PAD, y, "Stop Loss", f"{signal.sl:g}", DOWN)
    y += 84

    box_w = (WIDTH - PAD * 2 - 2 * 20) // 3
    labels = ("TP1", "TP2", "EXIT")
    labels = labels + tuple(f"TP{i + 1}" for i in range(3, len(signal.tps))) if len(signal.tps) > 3 else labels[:len(signal.tps)]
    for i, (label, tp) in enumerate(zip(labels, signal.tps)):
        x0 = PAD + i * (box_w + 20)
        _tp_box(draw, x0, y, box_w, tp_h, label, f"{tp:g}", i == 0)
    y += tp_h + 24

    if news_count:
        draw.line([(PAD, y), (WIDTH - PAD, y)], fill=(45, 60, 100), width=2)
        y += 20
        draw.text((PAD, y), "MARKET CONTEXT", font=_font("arialbd.ttf", 26), fill=TEXT_SUB, anchor="lm")
        y += 44
        for headline in news_context:
            for line in _wrap(draw, headline, _font("arial.ttf", 28), WIDTH - PAD * 2):
                draw.text((PAD, y), line, font=_font("arial.ttf", 28), fill=TEXT_MAIN, anchor="lm")
                y += 42
        y += 12
        draw.line([(PAD, y), (WIDTH - PAD, y)], fill=(45, 60, 100), width=2)
        y += 26

    footer_font = _font("arial.ttf", 26)
    footer = "SignalPilot @ 2026 · fully automated — not financial advice."
    draw.text((WIDTH // 2, y), footer, font=footer_font, fill=TEXT_SUB, anchor="mm")
    y += 46

    _watermark(img, H)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = out_dir / f"card_{signal.source_id or 'signal'}_{stamp}.png"
    img.save(out, "PNG")
    log.info("Card image rendered: %s (%dx%d)", out, WIDTH, H)
    return out


def _watermark(img: Image.Image, height: int) -> None:
    """Faint diagonal brand repeat so reposted cards are attributable."""
    draw = ImageDraw.Draw(img, "RGBA")
    font = _font("arialbd.ttf", 34)
    x = -200
    y = 120
    while x < img.size[0] + 200:
        if 0 <= y < height:
            tw = draw.textlength("SIGNALPILOT", font=font)
            draw.text(
                (x, y),
                "SIGNALPILOT",
                font=font,
                fill=(255, 255, 255, 14),
            )
            x += tw + 130
            y += 150
        else:
            y += 150
        if y > height:
            break