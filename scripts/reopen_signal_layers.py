"""Close any current single-position trade and reopen it as 0.01-lot layers."""
import asyncio
import sys

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, r"C:\Users\User\Documents\SignalPilotV1")
from dotenv import load_dotenv

load_dotenv(r"C:\Users\User\Documents\SignalPilotV1\.env")


async def main() -> int:
    from core.autotrade import _close_all, _live_positions, _ready, mt5
    from telethon import TelegramClient
    from core.config import TG_API_HASH, TG_API_ID, TG_PHONE, SIGNAL_SOURCES
    from core.parsers import parse_with_profile
    from core.autotrade import open_for_signal
    from dotenv import load_dotenv

    if not _ready():
        print("MT5 not ready")
        return 1

    closed = await asyncio.to_thread(_close_all, "XAUUSD-VIP")
    print("closed old blob:", closed, "lots")

    source = next(s for s in SIGNAL_SOURCES if s.source_id == "geom")
    client = TelegramClient("data/session", TG_API_ID, TG_API_HASH)
    if TG_PHONE:
        await client.start(phone=TG_PHONE)
    else:
        await client.start()
    try:
        try:
            entity = await client.get_entity(int(source.chat))
        except (ValueError, Exception):
            entity = await client.get_entity(source.chat.lstrip("@"))
        signal = raw = None
        async for msg in client.iter_messages(entity, limit=30):
            text = msg.raw_text or ""
            sig = parse_with_profile(source.parser_profile, text)
            if sig:
                signal, raw = sig, text
                break
        if not signal:
            print("no parseable GEO signal")
            return 1
        signal.source_id = source.source_id
        print("reopening as layers:", signal.direction.upper(), signal.symbol)
        result = await asyncio.to_thread(open_for_signal, signal, source.source_id, raw)
        print("RESULT:", result)
        live = await asyncio.to_thread(_live_positions, "XAUUSD-VIP")
        print("live positions:", len(live))
        for p in live:
            print("  ticket", p.ticket, "vol", p.volume, "sl", p.sl, "tp", p.tp)
        mt5.shutdown()
        return 0
    finally:
        await client.disconnect()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))