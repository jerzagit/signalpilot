"""
scripts/preview_last_signal.py
Fetch the most recent messages from a signal source, find the last one the
configured parser accepts, print the formatted card to the console, and POST
it to the forward channel. Used to preview how signals will look.

Usage (from the repo root, bot STOPPED so they share data/session):
    python scripts/preview_last_signal.py [--source geom] [--post]
"""

import argparse
import asyncio
import sys
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telethon import TelegramClient  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()


async def main() -> int:
    from core.config import TG_API_HASH, TG_API_ID, TG_PHONE, SIGNAL_SOURCES
    from core.forwarder import send_message
    from core.parsers import parse_with_profile

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="geom", help="source_id to preview")
    parser.add_argument("--post", action="store_true", help="also post the card")
    parser.add_argument("--news", action="store_true", help="attach gold/USD news context")
    args = parser.parse_args()

    source = next((s for s in SIGNAL_SOURCES if s.source_id == args.source), None)
    if not source:
        print(f"source '{args.source}' not in SIGNAL_SOURCES")
        return 1

    client = TelegramClient("data/session", TG_API_ID, TG_API_HASH)
    if TG_PHONE:
        await client.start(phone=TG_PHONE)
    else:
        await client.start()

    try:
        try:
            chat_id = int(source.chat)
            entity = await client.get_entity(chat_id)
        except (ValueError, Exception):
            entity = await client.get_entity(source.chat.lstrip("@"))
        title = getattr(entity, "title", None) or source.chat
        print(f"Scanning channel: {title}")

        found = None
        async for msg in client.iter_messages(entity, limit=50):
            text = msg.raw_text or ""
            signal = parse_with_profile(source.parser_profile, text)
            if signal:
                found = (signal, text)
                break

        if not found:
            print("No parseable GEO signal found in the last 50 messages.")
            return 0

        signal, raw = found
        signal.source_id = source.source_id
        signal.source_name = source.name
        signal.parser_profile = source.parser_profile

        card = build_card(signal, source.name, args.news)
        print("\n" + "=" * 46)
        print("PARSED SIGNAL CARD (how it will look in the channel)")
        print("=" * 46)
        print(card)
        print("=" * 46)
        print(f"raw message: {raw[:180]!r}")

        if args.post:
            ok = await asyncio.to_thread(send_message, card)
            print(f"\nPOSTED: {'OK' if ok else 'FAILED'}")
        return 0
    finally:
        await client.disconnect()


def build_card(signal, source_name: str, with_news: bool = False):
    from core.forwarder import build_signal_card

    news_context = None
    if with_news:
        from core.news import context_headlines

        news_context = context_headlines()
    return build_signal_card(signal, source_name, news_context=news_context)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))