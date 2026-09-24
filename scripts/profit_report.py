import asyncio, sys

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, r"C:\Users\User\Documents\SignalPilotV1")
from dotenv import load_dotenv

load_dotenv(r"C:\Users\User\Documents\SignalPilotV1\.env")


def main():
    from core import autotrade as at
    from core.config import MT5_ACCOUNT

    if not at._ready():
        print("MT5 not ready"); return
    mt5 = at.mt5
    info = mt5.account_info()
    from datetime import datetime
    from_date = datetime(2026, 9, 24, 0, 0)
    to_date = datetime(2026, 9, 26, 0, 0)
    raw = mt5.history_deals_get(from_date, to_date)
    print("total deals in window:", len(raw or []))
    deals = [d for d in (raw or []) if d.magic == at.MAGIC]
    deals.sort(key=lambda d: d.time)
    if not deals:
        print("no autotrade deals found"); return

    by_pos = {}
    traded = 0.0
    swap = comm = 0.0
    for d in deals:
        if d.type in (2, 3):  # balance/credit ops
            continue
        traded += d.profit or 0.0
        swap += d.swap or 0.0
        comm += d.commission or 0.0
        pid = d.position_id
        pos = by_pos.setdefault(pid, {"profit": 0.0, "swap": 0.0, "lots": 0.0,
                                      "symbol": d.symbol, "t_entry": d.time,
                                      "t_exit": d.time})
        pos["profit"] += d.profit or 0.0
        pos["swap"] += d.swap or 0.0
        pos["lots"] += d.volume
        if d.type in (0, 1):  # entry
            pos["t_entry"] = d.time
            pos["entry_ticket"] = d.ticket
        else:
            pos["t_exit"] = d.time
            pos["exit_ticket"] = d.ticket

    baseline = deals[0].balance if getattr(deals[0], "balance", None) is not None else None

    print("=== PER TRADE (magic %d) ===" % at.MAGIC)
    for pid, p in sorted(by_pos.items(), key=lambda kv: kv[1]["t_entry"]):
        pnl = p["profit"] + p["swap"]
        print("%s  lots %.2f  pnl %+.2f USD  (entry %s -> exit %s)" % (
            p["symbol"], p["lots"], pnl,
            __import__("time").strftime("%H:%M", __import__("time").localtime(p["t_entry"])),
            __import__("time").strftime("%H:%M", __import__("time").localtime(p["t_exit"]))))

    tot = traded + swap + comm

    # Baseline via arithmetic: balance_now = baseline + sum(all P&L in window)
    non_bal = [d for d in (raw or []) if d.type not in (2, 3)]
    tot_all = sum((d.profit or 0) + (d.swap or 0) + (d.commission or 0) for d in non_bal)
    balance_now = info.balance or 0
    baseline_window = balance_now - tot_all
    first_bot = min(d.time for d in deals)
    pre_manual = sum((d.profit or 0) + (d.swap or 0) + (d.commission or 0)
                     for d in non_bal if d.time < first_bot)
    baseline_first_trade = baseline_window + pre_manual

    print()
    print("Raw deals count          :", len(deals))
    print("Net traded P&L (bot)     : %+.2f USD" % (traded + swap))
    print("Commission (bot)         : %+.2f" % comm)
    print("TOTAL BOT PROFIT (today) : %+.2f USD" % tot)
    print("Balance at ~00:00 start  : %.2f USD" % baseline_window)
    print("Balance at first bot trade: %.2f USD" % baseline_first_trade)
    print("Balance now              : %.2f USD" % balance_now)
    print("Equity now               : %.2f USD" % (info.equity or 0))
    print("GROWTH vs first bot trade baseline: %+.2f%%" % (tot / baseline_first_trade * 100))
    mt5.shutdown()


if __name__ == "__main__":
    asyncio.run(asyncio.to_thread(main))