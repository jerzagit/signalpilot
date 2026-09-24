"""
core/news.py
Lightweight gold/USD news buffering for signal-card context.

Watches configured Telegram news channels, keeps headlines that match
NEWS_KEYWORDS in a rolling JSON buffer, and yields recent ones to attach to
published signal cards. Intent is context only — news is never forwarded on
its own.
"""

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

from core.config import (
    NEWS_BUFFER_MAX,
    NEWS_CONTEXT_HOURS,
    NEWS_CONTEXT_MAX,
    NEWS_KEYWORDS,
    NEWS_PROMO_BLOCKLIST,
)

log = logging.getLogger(__name__)

NEWS_BUFFER_FILE = Path("data/news_buffer.json")
NEWS_SEEN_FILE = Path("data/news_seen.json")

_WS = re.compile(r"\s+")
_URLS = re.compile(r"https?://\S+", re.I)
_MULTI_SPACE = re.compile(r"\s{2,}")
_MARKDOWN = re.compile(r"[*_`\[\]]")


@dataclass
class NewsItem:
    ts: float
    text: str


def clean_headline(text: str) -> str:
    """Strip links/noise and collapse whitespace for a tidy one-liner."""
    text = _URLS.sub("", text)
    text = _WS.sub(" ", text).strip().strip("\u200b\u200e\u200f")
    text = _MARKDOWN.sub("", text)
    return text[:160]


def matches_keywords(text: str, keywords: list[str] | None = None) -> bool:
    """True if the headline mentions any configured gold/USD keyword and is not
    promotional spam (see NEWS_PROMO_BLOCKLIST)."""
    lower = text.lower()
    if not any(kw in lower for kw in (keywords or NEWS_KEYWORDS)):
        return False
    return not any(term in lower for term in NEWS_PROMO_BLOCKLIST)


def _load_buffer() -> list[NewsItem]:
    try:
        raw = json.loads(NEWS_BUFFER_FILE.read_text(encoding="utf-8"))
        return [
            NewsItem(ts=float(item["ts"]), text=str(item["text"]))
            for item in raw
            if isinstance(item, dict) and item.get("text")
        ]
    except Exception:
        return []


def _save_buffer(items: list[NewsItem]) -> None:
    try:
        NEWS_BUFFER_FILE.parent.mkdir(parents=True, exist_ok=True)
        NEWS_BUFFER_FILE.write_text(
            json.dumps(
                [{"ts": item.ts, "text": item.text} for item in items],
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        log.warning("Could not persist news buffer: %s", exc)


_SEEN_LIMIT = 1000


def _load_seen() -> set[int]:
    try:
        return set(json.loads(NEWS_SEEN_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_seen(seen: set[int]) -> None:
    try:
        NEWS_SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        NEWS_SEEN_FILE.write_text(
            json.dumps(list(seen), indent=2), encoding="utf-8"
        )
    except Exception as exc:
        log.warning("Could not persist news seen set: %s", exc)


def add_headline(text: str) -> None:
    """Clean, filter, dedupe, and append a headline to the rolling buffer."""
    headline = clean_headline(text)
    if not headline or not matches_keywords(headline):
        return
    digest = hashlib.sha1(headline.encode("utf-8")).hexdigest()[:16]
    seen = _load_seen()
    if digest in seen:
        return
    seen.add(digest)
    if len(seen) > _SEEN_LIMIT:
        seen = set(list(seen)[-_SEEN_LIMIT:])
    _save_seen(seen)
    items = _load_buffer()
    items.append(NewsItem(ts=time.time(), text=headline))
    if len(items) > NEWS_BUFFER_MAX:
        items = items[-NEWS_BUFFER_MAX:]
    _save_buffer(items)
    log.info("News stored: %s", headline[:140])


def context_headlines(hours: int | None = None, limit: int | None = None) -> list[str]:
    """Most recent matching headlines (newest first) for signal-card context."""
    hours = NEWS_CONTEXT_HOURS if hours is None else hours
    limit = NEWS_CONTEXT_MAX if limit is None else limit
    cutoff = time.time() - hours * 3600
    recent = sorted(
        (item for item in _load_buffer() if item.ts >= cutoff and matches_keywords(item.text)),
        key=lambda item: item.ts,
        reverse=True,
    )
    return [item.text for item in recent[:limit]]