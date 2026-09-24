"""
core/db.py
SQLite mirror of MT5 auto-traded deals + GEO signal metadata, so the calendar
dashboard (dashboard/) never depends on MT5 terminal retention.

Schema mirrors the botsignal portal: signals (one per GEO tag) and trades (one
row per MT5 deal). Realized P&L is summed per day for the calendar view.
"""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path("data") / "trades.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    signal_id   TEXT PRIMARY KEY,
    received_at INTEGER,
    symbol      TEXT NOT NULL,
    direction   TEXT NOT NULL,
    entry       REAL,
    sl          REAL,
    tps         TEXT,
    layers      INTEGER,
    status      TEXT DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_ticket INTEGER UNIQUE,
    position_id INTEGER,
    ts          INTEGER,
    symbol      TEXT,
    tag         TEXT DEFAULT '',
    kind        TEXT,
    deal_type   INTEGER,
    volume      REAL,
    price       REAL,
    profit      REAL DEFAULT 0,
    swap        REAL DEFAULT 0,
    commission  REAL DEFAULT 0,
    fee         REAL DEFAULT 0,
    direction   TEXT
);
CREATE INDEX IF NOT EXISTS idx_trades_ts  ON trades(ts);
CREATE INDEX IF NOT EXISTS idx_trades_pos ON trades(position_id);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(_SCHEMA)


def _meta_get(conn, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _meta_set(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def record_signal(
    signal_id: str,
    symbol: str,
    direction: str,
    entry: float | None,
    sl: float | None,
    tps: list[float] | None,
    layers: int | None,
    received_at: int | None = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO signals (signal_id, received_at, symbol, direction, "
            "entry, sl, tps, layers, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open') "
            "ON CONFLICT(signal_id) DO UPDATE SET entry=excluded.entry, "
            "sl=excluded.sl, tps=excluded.tps, layers=excluded.layers",
            (
                signal_id,
                received_at,
                symbol,
                direction,
                entry,
                sl,
                json.dumps(tps) if tps else None,
                layers,
            ),
        )


def mark_signal_done(signal_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE signals SET status='done' WHERE signal_id = ?", (signal_id,)
        )


def upsert_deals(deals: list, ticket_to_tag: dict[int, str]) -> int:
    """Insert/ignore MT5 deal rows. Returns number of new rows stored."""
    if not deals:
        return 0
    rows = 0
    with get_conn() as conn:
        for d in deals:
            tag = ticket_to_tag.get(d.position_id, "")
            conn.execute(
                "INSERT OR IGNORE INTO trades (deal_ticket, position_id, ts, symbol, "
                "tag, kind, deal_type, volume, price, profit, swap, commission, "
                "fee, direction) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    d.ticket,
                    d.position_id,
                    d.time,
                    d.symbol,
                    tag,
                    "close" if d.entry in (1, 2) else "open",
                    d.type,
                    d.volume,
                    d.price,
                    d.profit or 0.0,
                    d.swap or 0.0,
                    d.commission or 0.0,
                    d.fee or 0.0,
                    "buy" if d.type in (0, 2, 100) else "sell",
                ),
            )
            rows += 1
        _meta_set(conn, "max_deal_ticket", str(max(d.ticket for d in deals)))
    return rows


def sync_from_mt5(mt5_module, magic: int, ticket_to_tag: dict[int, str] | None = None) -> int:
    """Pull deals since the last stored ticket and persist them."""
    import datetime as _dt

    ticket_to_tag = ticket_to_tag or {}
    with get_conn() as conn:
        last = int(_meta_get(conn, "max_deal_ticket") or 0)
    deals = mt5_module.history_deals_get(
        _dt.datetime(2024, 1, 1),
        _dt.datetime(2035, 1, 1),
    )
    deals = [d for d in (deals or []) if d.magic == magic] or []
    deals.sort(key=lambda d: d.time)
    fresh = [d for d in deals if d.ticket > last]
    return upsert_deals(fresh, ticket_to_tag)


def realized(p: sqlite3.Row) -> float:
    return float(p["profit"] or 0) + float(p["swap"] or 0) + float(p["commission"] or 0) + float(p["fee"] or 0)


def daily_pnl(days_all: bool = False):
    """Per-calendar-day realized P&L (all or only days with activity)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date(ts, 'unixepoch', 'localtime') AS day, "
            "SUM(profit + swap + commission + fee) AS pnl, "
            "SUM(CASE WHEN deal_type IN (1,2,4,5,6) THEN volume ELSE 0 END) AS vol, "
            "COUNT(*) AS deals "
            "FROM trades "
            "WHERE profit != 0 OR swap != 0 OR commission != 0 OR fee != 0 "
            "GROUP BY day ORDER BY day"
        ).fetchall()
    out = {r["day"]: {"pnl": round(float(r["pnl"] or 0), 2)} for r in rows}
    return out if days_all else [{"day": r["day"], "pnl": round(float(r["pnl"] or 0), 2)} for r in rows]


def equity_curve(from_baseline: float):
    """Daily balance = baseline + cumulative realized P&L by end of each day."""
    daily = daily_pnl(days_all=True)
    balance = from_baseline
    curve = []
    for day in sorted(daily):
        balance += daily[day]["pnl"]
        curve.append({"day": day, "balance": round(balance, 2)})
    return curve


def stats():
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS deals, SUM(profit + swap + commission + fee) AS pnl, "
            "SUM(CASE WHEN profit + swap + commission + fee > 0 THEN 1 ELSE 0 END) AS wins, "
            "SUM(CASE WHEN profit + swap + commission + fee < 0 THEN 1 ELSE 0 END) AS losses "
            "FROM trades WHERE profit != 0 OR swap != 0 OR commission != 0 OR fee != 0"
        ).fetchone()
        sig = conn.execute(
            "SELECT COUNT(*) AS n, SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS closed "
            "FROM signals"
        ).fetchone()
    return {
        "deals": row["deals"],
        "pnl": round(float(row["pnl"] or 0), 2),
        "wins": row["wins"] or 0,
        "losses": row["losses"] or 0,
        "signals": sig["n"],
        "signals_closed": sig["closed"] or 0,
    }


def recent_trades(limit: int = 50):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ts, symbol, tag, direction, kind, volume, price, profit, swap, "
            "commission, fee, position_id FROM trades "
            "WHERE profit != 0 OR swap != 0 OR commission != 0 OR fee != 0 "
            "ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "ts": r["ts"],
            "symbol": r["symbol"],
            "tag": r["tag"],
            "direction": r["direction"],
            "kind": r["kind"],
            "volume": r["volume"],
            "price": r["price"],
            "pnl": round(realized(r), 2),
        }
        for r in rows
    ]


def signals_for_month(year: int, month: int):
    import time as _time

    start = _time.mktime((year, month, 1, 0, 0, 0, 0, 0, -1))
    if month == 12:
        end = _time.mktime((year + 1, 1, 1, 0, 0, 0, 0, 0, -1))
    else:
        end = _time.mktime((year, month + 1, 1, 0, 0, 0, 0, 0, -1))
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT signal_id, received_at, symbol, direction, entry, sl, tps, "
            "layers, status FROM signals WHERE received_at >= ? AND received_at < ? "
            "ORDER BY received_at",
            (int(start), int(end)),
        ).fetchall()
    out = []
    for r in rows:
        out.append({
            "signal_id": r["signal_id"],
            "received_at": r["received_at"],
            "symbol": r["symbol"],
            "direction": r["direction"],
            "entry": r["entry"],
            "sl": r["sl"],
            "tps": json.loads(r["tps"]) if r["tps"] else [],
            "layers": r["layers"],
            "status": r["status"],
        })
    return out


init_db()