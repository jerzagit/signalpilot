"""
core/config.py
All configuration loaded from .env — single source of truth.

SignalPilotV1 does not execute trades. It listens to signal sources with your
Telegram user session and forwards parsed, formatted signals to your public
channel via a bot.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# ── Telegram user account (from https://my.telegram.org) ─────────────────────
TG_API_ID = int(os.getenv("TG_API_ID", "0"))
TG_API_HASH = os.getenv("TG_API_HASH", "")
TG_PHONE = os.getenv("TG_PHONE", "")

# ── Telegram bot (from @BotFather) — used only to POST to the channel ────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Admin chat(s) for silent ops notifications (comma-separated allowed).
ADMIN_CHATS = [
    c.strip()
    for c in os.getenv("ADMIN_CHATS", "").split(",")
    if c.strip()
]

# Destination channel for forwarded signals (@username or numeric-like -100…).
FORWARD_CHAT_ID = os.getenv("FORWARD_CHAT_ID", "@SignalPilot")

CHANNEL_HEADER = os.getenv("CHANNEL_HEADER", "SignalPilot")
FOOTER = os.getenv(
    "FOOTER",
    "Not financial advice. Trade at your own risk.",
)
ADMIN_LINE = os.getenv(
    "ADMIN_LINE",
    "Pm admin for auto-trade and link to see our dashboard.",
)

# Show the upstream provider name on published cards (default hides it so the
# channel reads as SignalPilot's own feed).
SHOW_SOURCE = os.getenv("SHOW_SOURCE", "false").lower() in {"1", "true", "yes", "on"}

# Runtime survival knobs
RECONNECT_ATTEMPTS = int(os.getenv("RECONNECT_ATTEMPTS", "5"))
RECONNECT_BACKOFF_SECS = int(os.getenv("RECONNECT_BACKOFF_SECS", "15"))

# Chart screencap on follow-up cards (Windows + Pillow + chart window open).
# Only the window whose title matches CHART_WINDOW_TITLE is captured; the bot
# never falls back to a full-screen grab, so it can't image whatever you're
# looking at. Default target is the TradingView browser tab.
CHART_SHOT_ENABLED = os.getenv(
    "CHART_SHOT_ENABLED", os.getenv("MT5_SCREENSHOT_ENABLED", "true")
).lower() in {"1", "true", "yes", "on"}
# Comma-separated title keywords used to locate the chart window (e.g. a
# TradingView browser tab).
CHART_WINDOW_TITLE = os.getenv(
    "CHART_WINDOW_TITLE", os.getenv("MT5_WINDOW_TITLE", "TradingView")
)

# Auto-trading via the MT5 terminal running on this PC (core/autotrade.py).
# Only GEO signals open trades; follow-ups manage them (TP1 = close half of
# multi-layer, TP2 = close about a quarter, Exit/SL/CLOSE ALL = close the rest).
AUTOTRADE_ENABLED = os.getenv("AUTOTRADE_ENABLED", "false").lower() in {
    "1", "true", "yes", "on",
}
# Risk budget: percent of equity that may be used as margin (//-sized in 0.01 lots).
RISK_PERCENT = float(os.getenv("RISK_PERCENT", "5"))
# Base lot size used for each layer.
AUTO_LOT_SIZE = float(os.getenv("AUTO_LOT_SIZE", "0.01"))
# Close layers automatically when price crosses GEO targets (TP1 = half the
# layers, TP2 = about a quarter, Exit = the rest) or only on Telegram follow-ups.
PRICE_TP_CLOSE = os.getenv("PRICE_TP_CLOSE", "true").lower() in {
    "1", "true", "yes", "on",
}
# How often (seconds) the price monitor polls live positions.
BE_POLL_SECS = int(os.getenv("BE_POLL_SECS", "5"))
# Optional MT5 terminal path override (auto-detected if empty).
MT5_TERMINAL_PATH = os.getenv("MT5_TERMINAL_PATH", "")
# Optional account-number guard: if set, the bot only trades when THIS account
# is the one logged into the terminal (avoids trading the wrong/real account).
MT5_ACCOUNT = os.getenv("MT5_ACCOUNT", "").strip()
# Optional auto-login credentials (used when the terminal is not already logged
# into the account). Keep in .env only — never commit.
MT5_LOGIN = os.getenv("MT5_LOGIN", "").strip()
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "").strip()
# Symbol mapping parsed name -> broker symbol (e.g. XAUUSD=XAUUSD-VIP).
MT5_SYMBOL_MAP = {
    k.strip(): v.strip()
    for pair in os.getenv("MT5_SYMBOL_MAP", "XAUUSD=XAUUSD").split(",")
    if "=" in pair
    for k, v in [pair.split("=", 1)]
}

# Account balance right before the first auto-traded signal — baseline for the
# dashboard's equity curve (sum of realized P&L is stacked on top of this).
ACCOUNT_BASELINE = float(os.getenv("ACCOUNT_BASELINE", "1416.55"))
# Keep the on-disk MT5 deal mirror (core/db.py) in sync as trades happen.
DB_SYNC_ENABLED = os.getenv("DB_SYNC_ENABLED", "true").lower() in {
    "1", "true", "yes", "on",
}


@dataclass(frozen=True)
class SignalSource:
    """Telegram signal source configuration."""
    source_id: str
    chat: str
    parser_profile: str = "default"
    name: str = ""


def _parse_signal_sources(raw: str) -> list[SignalSource]:
    """
    Parse SIGNAL_SOURCES.

        Format:
            source_id:chat:parser_profile:name

        Example:
            geom:-1002083967629:geom5:Geom V5,bobby:@Bobbylivetrade:bobby:BOBBY
    """
    sources: list[SignalSource] = []
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        parts = [p.strip() for p in item.split(":")]
        if len(parts) < 2:
            continue
        source_id = parts[0].lower().replace(" ", "_")
        chat = parts[1]
        parser_profile = parts[2].lower() if len(parts) > 2 and parts[2] else "default"
        name = parts[3] if len(parts) > 3 and parts[3] else source_id
        sources.append(SignalSource(source_id, chat, parser_profile, name))
    return sources


SIGNAL_SOURCES = _parse_signal_sources(os.getenv("SIGNAL_SOURCES", ""))

# ── News sources (free Telegram channels) ────────────────────────────────────
# Comma-separated list of Telegram channels broadcasting market news. Transformed
# headlines matching NEWS_KEYWORDS are kept in a rolling buffer and attached to
# signal cards as context. Format: source_id:chat (like signal sources).
NEWS_CHANNEL_HEADER = os.getenv("NEWS_CHANNEL_HEADER", "Market News")
NEWS_SOURCES = _parse_signal_sources(os.getenv("NEWS_SOURCES", ""))
for _news_source in NEWS_SOURCES:
    if _news_source.parser_profile == "default":
        object.__setattr__(_news_source, "parser_profile", "news")

NEWS_KEYWORDS = [
    kw.strip().lower()
    for kw in os.getenv(
        "NEWS_KEYWORDS",
        "gold,xau,silver,usd,dollar,fed,fomc,rate,inflation,treasury,yield,dxy",
    ).split(",")
    if kw.strip()
]
# Promo/hype terms that disqualify a headline even if a keyword matches
# (keeps paid-signal spam out of the context section).
NEWS_PROMO_BLOCKLIST = [
    term.strip().lower()
    for term in os.getenv(
        "NEWS_PROMO_BLOCKLIST",
        "pips,sniper,booom,boom,smashed,delivering results,pure price action,"
        "subscribe,join my,join our,vip,free signal,win rate,t.me/",
    ).split(",")
    if term.strip()
]
# Only headlines newer than this many hours are attached to a signal card.
NEWS_CONTEXT_HOURS = int(os.getenv("NEWS_CONTEXT_HOURS", "6"))
# Maximum number of headlines shown on one signal card.
NEWS_CONTEXT_MAX = int(os.getenv("NEWS_CONTEXT_MAX", "2"))
# Maximum headlines kept in the rolling buffer.
NEWS_BUFFER_MAX = int(os.getenv("NEWS_BUFFER_MAX", "30"))

# ── RSS/API news poller (e.g. Google News RSS for Reuters gold/USD) ──────────
# Comma-separated RSS (or JSON) feed URLs polled on a timer. Headlines are
# filtered through the same keyword + promo logic as Telegram news channels.
# Leave empty to disable the poller.
NEWS_RSS_QUERIES = [
    q.strip()
    for q in os.getenv(
        "NEWS_RSS_QUERIES",
        "https://news.google.com/rss/search?q=site:reuters.com+gold&hl=en-US&gl=US&ceid=US:en,"
        "https://news.google.com/rss/search?q=site:reuters.com+dollar&hl=en-US&gl=US&ceid=US:en,"
        "https://news.google.com/rss/search?q=site:reuters.com+fed+rate&hl=en-US&gl=US&ceid=US:en",
    ).split(",")
    if q.strip()
]
# Seconds between news poll cycles.
NEWS_POLL_SECS = int(os.getenv("NEWS_POLL_SECS", "300"))
# Maximum headline count pulled from one feed per poll.
NEWS_RSS_LIMIT = int(os.getenv("NEWS_RSS_LIMIT", "15"))

# ── Signal card images ───────────────────────────────────────────────────────
# Publish parsed signals as rendered PNG cards instead of raw text, so the feed
# is harder to copy/scrape. Falls back to text if rendering fails.
CARD_IMAGE_ENABLED = os.getenv("CARD_IMAGE_ENABLED", "true").lower() in {
    "1", "true", "yes", "on",
}
CARD_IMAGE_DIR = os.getenv("CARD_IMAGE_DIR", "data/cards")