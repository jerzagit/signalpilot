"""
core/listener.py
Telethon client — watches configured Telegram signal sources as YOUR account.
No admin rights needed. Works as long as you are a group/channel member and can
see the messages.

Every parsed entry is forwarded to the SignalPilot channel as a formatted card.
Recognized follow-ups (TP/SL hit, close all, collect, …) are forwarded with the
symbol of the last signal seen on the same source, plus a live chart screenshot
of the chart window (default: TradingView tab) when it is open — see
core/grabshot.py. No full-screen capture ever happens.
"""

import asyncio
import json
import logging
import time
from pathlib import Path

from telethon import TelegramClient, events
from telethon import utils as tg_utils

from core.card_image import render_signal_card
from core.config import (
    ADMIN_CHATS,
    AUTOTRADE_ENABLED,
    TG_API_ID,
    TG_API_HASH,
    TG_PHONE,
    SIGNAL_SOURCES,
    NEWS_SOURCES,
    NEWS_RSS_QUERIES,
    NEWS_POLL_SECS,
    CARD_IMAGE_ENABLED,
    CARD_IMAGE_DIR,
    CHART_SHOT_ENABLED,
)
from core.forwarder import (
    build_followup_card,
    build_signal_card,
    notify_admin,
    send_message,
    send_photo_with_caption,
)
from core.autotrade import handle_followup as autotrade_followup
from core.autotrade import open_for_signal as autotrade_open
from core.autotrade import run_manager_loop as run_autotrade_loop
from core.grabshot import capture_chart
from core.news import add_headline, context_headlines
from core.parsers import parse_with_profile
from core.rss_news import poll_news_loop
from core.signal import attach_source_context, parse_followup_alert

log = logging.getLogger(__name__)

LAST_SIGNALS_FILE = Path("data/last_signals.json")

_TRADE_LOCK = asyncio.Lock()


def _load_last_signals() -> dict[str, dict]:
    try:
        return json.loads(LAST_SIGNALS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_last_signals(last_signals: dict[str, dict]) -> None:
    try:
        LAST_SIGNALS_FILE.parent.mkdir(parents=True, exist_ok=True)
        LAST_SIGNALS_FILE.write_text(
            json.dumps(last_signals, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        log.warning("Could not persist last signals: %s", exc)


async def resolve_group_for_target(client: TelegramClient, target: str):
    """Resolve one Telegram group/channel target (username or numeric ID)."""
    target = target.strip()
    try:
        integer_id = int(target)
        entity = await client.get_entity(integer_id)
        name = getattr(entity, "title", None) or getattr(entity, "username", str(entity))
        log.info("Resolved Telegram source by numeric ID: %s", name)
        return entity
    except (ValueError, Exception):
        pass

    entity = await client.get_entity(target.lstrip("@"))
    name = getattr(entity, "title", None) or getattr(entity, "username", str(entity))
    log.info("Resolved Telegram source by username: %s", name)
    return entity


async def resolve_sources(client: TelegramClient):
    """Resolve every configured Telegram source into a Telethon entity."""
    resolved = []
    for source in SIGNAL_SOURCES:
        entity = await resolve_group_for_target(client, source.chat)
        peer_id = tg_utils.get_peer_id(entity)
        resolved.append((source, entity, peer_id))
        name = getattr(entity, "title", None) or getattr(entity, "username", str(entity))
        log.info(
            "Resolved source %s (%s) by %s: %s",
            source.source_id, source.parser_profile, source.chat, name,
        )
    return resolved


async def start_listener() -> None:
    """Start Telethon, resolve sources, listen, and forward parsed signals."""
    client = TelegramClient("data/session", TG_API_ID, TG_API_HASH)
    if TG_PHONE:
        await client.start(phone=TG_PHONE)
    else:
        await client.start()

    try:
        resolved_sources = await resolve_sources(client)
    except Exception as exc:
        log.error("Could not resolve configured signal source: %s", exc)
        raise

    if not resolved_sources:
        log.error("No signal sources configured. Set SIGNAL_SOURCES in .env.")
        return

    source_by_peer_id = {peer_id: source for source, _, peer_id in resolved_sources}
    source_by_entity_id = {
        getattr(entity, "id", None): source for source, entity, _ in resolved_sources
    }
    group_entities = [entity for _, entity, _ in resolved_sources]

    resolved_news = []
    for news_source in NEWS_SOURCES:
        try:
            entity = await resolve_group_for_target(client, news_source.chat)
        except Exception as exc:
            log.warning(
                "Skipping news source %s (%s): %s",
                news_source.source_id, news_source.chat, exc,
            )
            continue
        news_peer_id = tg_utils.get_peer_id(entity)
        resolved_news.append((news_source, entity, news_peer_id))
        log.info(
            "Resolved news source %s by %s: %s",
            news_source.source_id, news_source.chat,
            getattr(entity, "title", None) or news_source.name,
        )
        group_entities.append(entity)
    news_by_peer_id = {peer_id: source for source, _, peer_id in resolved_news}
    news_by_entity_id = {
        getattr(entity, "id", None): source for source, entity, _ in resolved_news
    }
    last_signals = _load_last_signals()

    me = await client.get_me()
    watch_lines = []
    for source, entity, _ in resolved_sources:
        title = getattr(entity, "title", None) or getattr(entity, "username", source.chat)
        watch_lines.append(f"- `{source.source_id}` → {title} ({source.parser_profile})")
    news_lines = []
    for news_source, entity, _ in resolved_news:
        title = getattr(entity, "title", None) or news_source.name
        news_lines.append(f"- `{news_source.source_id}` → {title} (news)")

    if ADMIN_CHATS:
        await asyncio.to_thread(
            notify_admin,
            "🟢 *SignalPilotV1 is LIVE!*\n"
            f"👤 Listening as `{me.first_name}`\n"
            "📡 Watching:\n" + "\n".join(watch_lines)
            + ("\n📰 News:\n" + "\n".join(news_lines) if news_lines else ""),
        )
    log.info("Listening on %d source(s) as %s", len(group_entities), me.first_name)

    if NEWS_RSS_QUERIES:
        asyncio.create_task(poll_news_loop())
        log.info("News RSS poller active on %d feed(s) every %ss.",
                 len(NEWS_RSS_QUERIES), NEWS_POLL_SECS)

    if AUTOTRADE_ENABLED:
        asyncio.create_task(run_autotrade_loop())
        log.info("Auto-trader active on GEO signals (MT5 manager loop running).")

    @client.on(events.NewMessage(chats=group_entities))
    async def on_new_message(event):
        text = event.raw_text or ""
        news_source = (
            news_by_peer_id.get(event.chat_id)
            or news_by_entity_id.get(getattr(event.chat, "id", None))
        )
        if news_source:
            add_headline(text)
            log.info("News [%s]: %s", news_source.source_id, text[:140])
            return

        source = (
            source_by_peer_id.get(event.chat_id)
            or source_by_entity_id.get(getattr(event.chat, "id", None))
            or SIGNAL_SOURCES[0]
        )
        log.info("Message [%s]: %s", source.source_id, text[:120])

        followup = parse_followup_alert(text)
        if followup:
            last = last_signals.get(source.source_id)
            attach_source_context(
                followup,
                symbol=last.get("symbol") if last else None,
                direction=last.get("direction") if last else None,
            )
            log.info(
                "Follow-up [%s]: %s symbol=%s direction=%s",
                source.source_id, followup.action, followup.symbol, followup.direction,
            )
            if AUTOTRADE_ENABLED:
                async with _TRADE_LOCK:
                    t0 = time.perf_counter()
                    result = await asyncio.to_thread(
                        autotrade_followup, followup, source.source_id, text
                    )
                if result:
                    log.info(
                        "Autotrade follow-up [%s]: %s (%.1fms)",
                        source.source_id, result, (time.perf_counter() - t0) * 1000,
                    )
            card = build_followup_card(followup, source.name, text)
            published = False
            if CHART_SHOT_ENABLED:
                image = await asyncio.to_thread(capture_chart)
                if image:
                    published = await asyncio.to_thread(
                        send_photo_with_caption, str(image), card
                    )
            if not published:
                published = await asyncio.to_thread(send_message, card)
            log.info("Follow-up forwarded [%s]: %s", source.source_id, "OK" if published else "FAILED")
            if ADMIN_CHATS:
                await asyncio.to_thread(
                    notify_admin,
                    f"📢 Forwarded follow-up: `{followup.action}` "
                    + (f"({followup.symbol})" if followup.symbol else "")
                    + (f" + chart" if published else ""),
                )
            return

        signal = parse_with_profile(source.parser_profile, text)
        if not signal:
            log.debug("Not a trade signal, skipping.")
            return

        signal.source_id = source.source_id
        signal.source_name = source.name
        signal.parser_profile = source.parser_profile

        last_signals[source.source_id] = {
            "symbol": signal.symbol,
            "direction": signal.direction,
        }
        _save_last_signals(last_signals)

        if AUTOTRADE_ENABLED:
            async with _TRADE_LOCK:
                t0 = time.perf_counter()
                result = await asyncio.to_thread(
                    autotrade_open, signal, source.source_id, text
                )
            if result:
                log.info(
                    "Autotrade open [%s]: %s (%.1fms)",
                    source.source_id, result, (time.perf_counter() - t0) * 1000,
                )

        headline_context = context_headlines() if (resolved_news or NEWS_RSS_QUERIES) else None
        card = build_signal_card(
            signal,
            source.name,
            news_context=headline_context,
        )
        if CARD_IMAGE_ENABLED:
            try:
                image = await asyncio.to_thread(
                    render_signal_card, signal, headline_context, CARD_IMAGE_DIR
                )
            except Exception as exc:
                log.warning("Card image render failed, using text: %s", exc)
                image = None
            if image:
                caption = (
                    f"{'🟢' if signal.direction == 'buy' else '🔴'} "
                    f"{signal.direction.upper()} {signal.symbol} · "
                    f"Entry {signal.entry_low:g} · SL {signal.sl:g}"
                )
                ok = await asyncio.to_thread(send_photo_with_caption, str(image), caption)
                if ok:
                    log.info(
                        "Forwarded image [%s]: %s %s → OK",
                        source.source_id, signal.symbol, signal.direction.upper(),
                    )
                    if ADMIN_CHATS:
                        await asyncio.to_thread(
                            notify_admin,
                            f"📢 Forwarded: `{signal.symbol}` {signal.direction.upper()} (image card)",
                        )
                    return
        ok = await asyncio.to_thread(send_message, card)
        log.info(
            "Forwarded [%s]: %s %s → %s",
            source.source_id, signal.symbol, signal.direction.upper(), "OK" if ok else "FAILED",
        )
        if ADMIN_CHATS:
            await asyncio.to_thread(
                notify_admin,
                f"📢 Forwarded: `{signal.symbol}` {signal.direction.upper()} entry "
                f"`{signal.entry_low:g}` (OK)" if ok else f"send failed",
            )

    await client.run_until_disconnected()