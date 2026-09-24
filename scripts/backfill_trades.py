"""Backfill data/trades.db from MT5 deal history (one-time / refresh)."""
import asyncio
import sys

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, r"C:\Users\User\Documents\SignalPilotV1")
from dotenv import load_dotenv

load_dotenv(r"C:\Users\User\Documents\SignalPilotV1\.env")


def main():
    from core import autotrade as at
    from core.config import ACCOUNT_BASELINE, MT5_ACCOUNT
    from core import db
    from core.db import record_signal, sync_from_mt5, equity_curve

    if not at._ready():
        print("MT5 not ready"); return
    mt5 = at.mt5

    # Map every ticket that appears in autotrade state to its GEO tag.
    state = at._state()
    ticket_to_tag = {}
    for trade in state.values():
        for t in at._trade_tickets(trade):
            ticket_to_tag[int(t)] = trade["tag"]
        if trade.get("ticket"):
            ticket_to_tag[int(trade["ticket"])] = trade["tag"]

    added = sync_from_mt5(mt5, at.MAGIC, ticket_to_tag)
    print("synced new deal rows:", added)

    # Rebuild the signals table from state so tags/levels are complete.
    for trade in state.values():
        record_signal(
            trade["tag"], trade["symbol"], trade["direction"],
            trade.get("entry_signal"), trade.get("sl_geos"),
            trade.get("tps"), trade.get("layers"),
            received_at=trade.get("open_ts"),
        )

    s = db.stats()
    print("stats:", s)
    curve = equity_curve(ACCOUNT_BASELINE)
    print(f"equity curve ({len(curve)} days):")
    for c in curve:
        print("  ", c["day"], f"${c['balance']:,.2f}")
    mt5.shutdown()


if __name__ == "__main__":
    asyncio.run(asyncio.to_thread(main))