"""
core/grabshot.py
Windows-only helper that captures a screenshot of the chart window (default:
a TradingView browser tab) and returns the PNG path, so a follow-up card can
include a live chart image.

Only the matched window is ever captured — there is no full-screen fallback,
so the bot can never image whatever the user happens to be looking at.
Requires Pillow (pip install -r requirements.txt).
"""

import ctypes
import logging
import re
import time
from pathlib import Path
from ctypes import wintypes

from core.config import CHART_WINDOW_TITLE

log = logging.getLogger(__name__)

_user32 = ctypes.windll.user32
_user32.SetProcessDPIAware()


def _keywords() -> list[str]:
    return [k.strip().lower() for k in CHART_WINDOW_TITLE.split(",") if k.strip()] or [
        "tradingview"
    ]


def _find_window() -> int:
    """Return the hwnd of the chart window, else 0.

    1. Exact title-keyword match (CHART_WINDOW_TITLE, e.g. "TradingView").
    2. Fallback: a browser tab whose live title looks like a chart — a price
       number plus a separate title segment (TradingView tabs are titled
       "SYMBOL PRICE ... - <browser>", without the word "TradingView").
    """
    matches: list[int] = []
    charty: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd, lparam):
        if not _user32.IsWindowVisible(hwnd):
            return True
        length = _user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value
        if any(keyword in title.lower() for keyword in _keywords()):
            matches.append(hwnd)
        elif _looks_like_chart_tab(title):
            charty.append(hwnd)
        return True

    _user32.EnumWindows(enum_proc, 0)
    if matches:
        return matches[0]
    if charty:
        return charty[0]
    return 0


def _looks_like_chart_tab(title: str) -> bool:
    """Is this a browser tab whose live title looks like a chart?

    TradingView page-title format has no 'TradingView' text:
    'XAUUSD 4,257.255 ▼ −0.7% Apr 2023 Last Week - Google Chrome'.
    We look for a price number and a ' - <browser>' suffix.
    """
    if not re.search(r"\b\d[\d,]*\.\d{2,4}\b", title):
        return False
    return bool(
        re.search(
            r" - (?:Google )?(?:Chrome|Opera|Edge|Firefox|Brave|Vivaldi)\b",
            title,
            re.IGNORECASE,
        )
    )


def _window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return (rect.left, rect.top, rect.right, rect.bottom)


def _bring_to_front(hwnd: int) -> None:
    try:
        _user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        _user32.SetForegroundWindow(hwnd)
        time.sleep(0.6)
    except Exception:
        log.debug("Could not bring MT5 window to front.", exc_info=True)


def capture_chart(out_dir: str | Path = "data/screenshots") -> Path | None:
    """Capture the chart window and return the saved PNG path.

    Never falls back to a full-screen grab: if the chart window is not found
    (or cannot be captured), no screenshot is taken so we never image whatever
    the user happens to be looking at (browser, personal apps, etc.).
    """
    try:
        from PIL import ImageGrab
    except Exception:
        log.warning("Pillow is not installed — skipping screenshot (pip install -r requirements.txt).")
        return None

    hwnd = _find_window()
    if not hwnd:
        log.info(
            "No chart window found (title contains '%s') — skipping screenshot (full-screen capture disabled).",
            CHART_WINDOW_TITLE,
        )
        return None

    _bring_to_front(hwnd)
    bbox = _window_rect(hwnd)
    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        log.warning("Chart window rect is empty %s — skipping screenshot.", bbox)
        return None
    log.info("Capturing chart window region: %s", bbox)

    try:
        shot = ImageGrab.grab(bbox=bbox, all_screens=True)
    except Exception as exc:
        log.error("Screenshot failed: %s", exc)
        return None

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"chart_{int(time.time())}.png"
    shot.save(path)
    log.info("Screenshot saved: %s", path)
    return path