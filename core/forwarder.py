"""
core/forwarder.py
Builds subscriber-facing message cards and posts them to the signal channel
using the Telegram Bot API (sendMessage). Network calls are synchronous so
the async listener runs them through asyncio.to_thread.

Cards use SignalPilot's own wording and layout (not the provider's original
format) so the channel reads as one clean, consistent feed.
"""

import logging
import secrets
from datetime import datetime
from pathlib import Path

import requests

from core.config import (
    ADMIN_LINE,
    BOT_TOKEN,
    FORWARD_CHAT_ID,
    CHANNEL_HEADER,
    FOOTER,
    SHOW_SOURCE,
)
from core.signal import FollowUpAlert, Signal

log = logging.getLogger(__name__)

PARSE_MODE = "Markdown"
_BORDER = "▬" * 16

_TP_LABELS = ("TP1", "TP2", "Exit")


def _level_label(level: int) -> str:
    """Target name for a 1-based level, matching the card's own label set."""
    if 0 < level <= len(_TP_LABELS):
        return _TP_LABELS[level - 1]
    return f"TP{level}"


def _fmt_price(value: float) -> str:
    """Format a price with the decimals its magnitude implies (gold ≈2, fx ≈5)."""
    value = float(value)
    if value < 10:
        return f"{value:.5f}"
    if value < 100:
        return f"{value:.3f}"
    return f"{value:.2f}"


def _call_id() -> str:
    """Short unique id: SP-YYMMDD-XXXX."""
    return f"SP-{datetime.now():%y%m%d}-{secrets.token_hex(2).upper()}"


def _timestamp_text() -> str:
    """Current time like '24 Sep 4:47pm' — neutral branding, no provider clues."""
    now = datetime.now()
    hour12 = now.hour % 12 or 12
    ampm = "am" if now.hour < 12 else "pm"
    return f"{now.day} {now.strftime('%b')} {hour12}:{now.minute:02d}{ampm}"


def _footer() -> str:
    return (
        f"{CHANNEL_HEADER} @ {datetime.now():%Y} · fully automated\n"
        f"{FOOTER}\n"
        f"{ADMIN_LINE}"
    )


_FOLLOWUP_LABELS = {
    "setup_failed": "❌ Setup voided",
    "tp_hit": "✅ TP hit",
    "sl_hit": "❌ SL hit",
    "close_all": "🔒 Close all positions now",
    "collect_profit": "💰 Collect targets",
    "early_tp": "💰 Collect targets",
    "close_half": "✂️ Trim position",
    "breakeven": "🛡 Protect entry",
}


def build_signal_card(
    signal: Signal,
    source_label: str = "",
    show_source: bool | None = None,
    news_context: list[str] | None = None,
) -> str:
    show_source = SHOW_SOURCE if show_source is None else show_source
    glyph = "🟢" if signal.direction == "buy" else "🔴"
    zone = (
        _fmt_price(signal.entry_low)
        if signal.entry_low == signal.entry_high
        else f"{_fmt_price(signal.entry_low)} {'–'} {_fmt_price(signal.entry_high)}"
    )

    rows = [
        f"ID            : `{_call_id()}`",
        f"Entry         : `{zone}`",
        f"Stop Loss (SL): `{_fmt_price(signal.sl)}`",
    ]
    for index, tp in enumerate(signal.tps):
        label = _level_label(index + 1)
        rows.append(f"{label:<13} : `{_fmt_price(tp)}`")

    headline_rows = []
    if news_context:
        headline_rows = [f"📰 {line}" for line in news_context]

    credit = f"\nSource: `{source_label}`" if (source_label and show_source) else ""
    news_block = (
        "\n" + "\n".join(headline_rows)
        if headline_rows
        else ""
    )
    return (
        f"{glyph} {signal.direction.upper()} *{signal.symbol}*\n"
        f"{_BORDER}\n"
        + "\n".join(rows)
        + f"{news_block}\n"
        f"{_BORDER}\n"
        f"⏱ {_timestamp_text()}\n"
        f"{_footer()}{credit}"
    )


def build_followup_card(alert: FollowUpAlert, source_label: str = "", raw_text: str = "") -> str:
    label = _FOLLOWUP_LABELS.get(alert.action, alert.action.replace("_", " ").title())
    if alert.action == "tp_hit" and getattr(alert, "level", 0):
        label = f"✅ {_level_label(int(alert.level))} hit"
    details = alert.symbol or "Position"
    return (
        f"{CHANNEL_HEADER} · {label}\n"
        f"{_BORDER}\n"
        f"{details}\n"
        f"{_BORDER}\n"
        f"⏱ {_timestamp_text()}\n"
        f"{_BORDER}\n"
        f"{_footer()}"
    )


def send_message(
    text: str,
    chat_id: str = "",
    chat_id_override: str | None = None,
) -> bool:
    """Post a message to the forward channel (or ADMIN chat when chat_id given)."""
    target = chat_id_override or chat_id or FORWARD_CHAT_ID
    if not BOT_TOKEN or not target:
        log.error("Forward skipped: BOT_TOKEN or target chat is missing.")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": target, "text": text, "parse_mode": PARSE_MODE},
            timeout=20,
        )
    except requests.RequestException as exc:
        log.error("Telegram request failed: %s", exc)
        return False
    if resp.status_code != 200:
        log.error("Telegram send failed: %s", resp.text[:500])
        return False
    return True


def send_photo_with_caption(
    image_path: str | Path,
    caption: str,
    chat_id: str = "",
    chat_id_override: str | None = None,
) -> bool:
    """Send an image with a caption to the forward channel (Bot API sendPhoto)."""
    target = chat_id_override or chat_id or FORWARD_CHAT_ID
    if not BOT_TOKEN or not target:
        log.error("Photo skipped: BOT_TOKEN or target chat is missing.")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    try:
        with open(image_path, "rb") as handle:
            files = {"photo": (Path(image_path).name, handle, "image/png")}
            data = {"chat_id": target, "caption": caption, "parse_mode": PARSE_MODE}
            resp = requests.post(url, data=data, files=files, timeout=30)
    except (requests.RequestException, OSError) as exc:
        log.error("Telegram photo send failed: %s", exc)
        return False
    if resp.status_code != 200:
        log.error("Telegram photo send failed: %s", resp.text[:500])
        return False
    return True


def notify_admin(text: str) -> bool:
    """Silent ops notification to all admin chats (no parse mode errors)."""
    ok = True
    for chat_id in _admin_chats():
        if not send_message(text, chat_id=chat_id):
            ok = False
    return ok


def _admin_chats() -> list[str]:
    from core.config import ADMIN_CHATS

    return ADMIN_CHATS