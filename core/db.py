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
    status      TEXT DEFAULT 'open',
    exit        TEXT DEFAULT ''
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
        cols = {r[1] for r in conn.execute("PRAGMA table_info(signals)")}
        if "exit" not in cols:
            conn.execute("ALTER TABLE signals ADD COLUMN exit TEXT DEFAULT ''")


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


def mark_signal_exit(signal_id: str, exit_label: str) -> None:
    """Record how a signal finished (TP1/TP2/TP3/SL/MAN/EXT) and close it."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE signals SET status='done', exit=? WHERE signal_id = ?",
            (exit_label, signal_id),
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


def close_level(price: float, tps: list[float], sl: float | None, direction: str) -> str:
    """Which exit a close price maps to: highest TP reached (with a small
    touch-tolerance for market-close overshoot), SL, or MAN (manual/other)."""
    price = float(price)
    tol = 0.5  # price units a fill may overshoot the TP (XAUUSD ~5 pips)
    reached = []
    for i, tp in enumerate(tps or [], start=1):
        if direction == "buy" and price >= float(tp) - tol:
            reached.append(i)
        elif direction == "sell" and price <= float(tp) + tol:
            reached.append(i)
    if reached:
        return f"TP{max(reached)}"
    if sl is not None:
        if (direction == "buy" and price <= float(sl)) or (
            direction == "sell" and price >= float(sl)
        ):
            return "SL"
    return "MAN"


_LEVEL_LABELS = ("TP1", "TP2", "Exit")


def _level_rank(label: str) -> int:
    """Ordering for level badges: Exit is the final target (highest)."""
    if label == "Exit":
        return 10**6
    if label.startswith("TP"):
        return int(label[2:]) or 0
    return 0


def close_level(price: float, tps: list[float], sl: float | None, direction: str) -> str:
    """Which exit a close price maps to: highest target reached (with a small
    touch-tolerance for market-close overshoot), SL, or MAN (manual/other)."""
    price = float(price)
    tol = 0.5  # price units a fill may overshoot the TP (XAUUSD ~5 pips)
    reached = []
    for i, tp in enumerate(tps or [], start=1):
        if direction == "buy" and price >= float(tp) - tol:
            reached.append(i)
        elif direction == "sell" and price <= float(tp) + tol:
            reached.append(i)
    if reached:
        index = max(reached) - 1
        return _LEVEL_LABELS[index] if index < len(_LEVEL_LABELS) else f"TP{index + 1}"
    if sl is not None:
        if (direction == "buy" and price <= float(sl)) or (
            direction == "sell" and price >= float(sl)
        ):
            return "SL"
    return "MAN"


def grouped_trades(limit_groups: int = 50, from_ts: int | None = None, to_ts: int | None = None):
    """Trades grouped by signal tag, with per-layer open/close detail rows.

    from_ts/to_ts (unix) restrict to signals received within that window (so a
    "day on the calendar" shows exactly that day's signals).
    """
    import time as _time

    with get_conn() as conn:
        sigs = {
            r["signal_id"]: r
            for r in conn.execute("SELECT * FROM signals").fetchall()
        }
        if from_ts is not None or to_ts is not None:
            lo = int(from_ts) if from_ts is not None else 0
            hi = int(to_ts) if to_ts is not None else 2**62
            sigs = {
                sid: s
                for sid, s in sigs.items()
                if lo <= (s["received_at"] or 0) < hi
            }
            allow_tags = set(sigs)
        else:
            allow_tags = None
        if allow_tags is not None:
            rows = conn.execute(
                "SELECT * FROM trades WHERE tag != '' AND tag IN ({}) ORDER BY ts".format(
                    ",".join("?" * len(allow_tags))
                ),
                sorted(allow_tags),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trades WHERE tag != '' ORDER BY ts"
            ).fetchall()

    groups: dict[str, dict] = {}
    for r in rows:
        tag = r["tag"]
        g = groups.setdefault(
            tag,
            {
                "tag": tag,
                "received_at": None,
                "symbol": r["symbol"],
                "direction": r["direction"],
                "entry": None,
                "sl": None,
                "tps": [],
                "layers": None,
                "status": "",
                "exit": "",
                "opens": {},
                "closes": {},
            },
        )
        if r["kind"] == "open":
            g["opens"][r["position_id"]] = r
        else:
            g["closes"].setdefault(r["position_id"], []).append(r)

    out = []
    for tag, g in groups.items():
        sig = sigs.get(tag)
        if sig:
            g["received_at"] = sig["received_at"]
            g["symbol"] = sig["symbol"]
            g["direction"] = sig["direction"]
            g["entry"] = sig["entry"]
            g["sl"] = sig["sl"]
            g["tps"] = json.loads(sig["tps"]) if sig["tps"] else []
            g["layers"] = sig["layers"]
            g["status"] = sig["status"]
            g["exit"] = sig["exit"] or ""

        layer_rows = []
        level_counts: dict[str, int] = {}
        total_pnl = 0.0
        total_volume = 0.0
        positions = list(g["opens"].keys()) or list(g["closes"].keys())
        positions.sort(key=lambda p: g["opens"][p]["ts"] if p in g["opens"] else 0)
        for p in positions:
            open_r = g["opens"].get(p)
            closes = g["closes"].get(p, [])
            layer = {
                "position_id": p,
                "volume": float(open_r["volume"] if open_r else (closes[0]["volume"] if closes else 0)),
                "open_ts": open_r["ts"] if open_r else None,
                "open_price": open_r["price"] if open_r else None,
                "closes": [],
                "pnl": 0.0,
                "level": "",
            }
            for cl in closes:
                level = close_level(cl["price"], g["tps"], g["sl"], g["direction"])
                layer["closes"].append({
                    "ts": cl["ts"],
                    "price": cl["price"],
                    "volume": cl["volume"],
                    "pnl": round(realized(cl), 2),
                    "level": level,
                })
                layer["pnl"] = round(layer["pnl"] + realized(cl), 2)
                layer["level"] = level
                level_counts[level] = level_counts.get(level, 0) + 1
                total_pnl += realized(cl)
            total_volume += layer["volume"]
            layer_rows.append(layer)

        badges = sorted(
            level_counts,
            key=lambda lvl: (_level_rank(lvl) <= 0, -_level_rank(lvl)),
        )
        hit_levels = [l for l in badges if _level_rank(l) > 0]
        exit_label = (
            max(hit_levels, key=_level_rank)
            if hit_levels
            else (badges[0] if badges else "")
        )
        g["exit"] = g["exit"] or exit_label
        g["badges"] = badges
        g["layers_detail"] = layer_rows
        g["pnl"] = round(total_pnl, 2)
        g["volume"] = round(total_volume, 2)
        g["opened_at"] = min((l["open_ts"] for l in layer_rows if l["open_ts"]), default=None)
        g["last_close_at"] = max(
            (c["ts"] for l in layer_rows for c in l["closes"]), default=None
        )
        g.pop("opens", None)
        g.pop("closes", None)
        out.append(g)

    out.sort(key=lambda g: g["opened_at"] or 0, reverse=True)
    return out[:limit_groups]


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
