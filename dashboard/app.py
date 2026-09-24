"""
dashboard/app.py
SignalPilot Calendar Dashboard — Flask app following the botsignal portal UI.

    Direct: http://127.0.0.1:5001

Reads the SQLite mirror (core/db.py) maintained by core/autotrade.py; optional
live MT5 account probe for the top-right balance.
"""

import calendar as pycal
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, jsonify, render_template, request

from core import db
from core.config import ACCOUNT_BASELINE, AUTOTRADE_ENABLED, MT5_ACCOUNT, MT5_SERVER

app = Flask(__name__, template_folder="templates")


@app.template_filter("pycal_month_name")
def _pycal_month_name(month: int) -> str:
    return pycal.month_name[int(month)]


def _mode() -> str:
    server = MT5_SERVER or ""
    return "DEMO" if "demo" in server.lower() else "LIVE"


def _month_bounds(year: int, month: int):
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


def _calendar_view(year: int, month: int) -> dict:
    _, num_days = pycal.monthrange(year, month)
    first_wd = pycal.monthrange(year, month)[0]  # Mon=0
    today = date.today()

    daily = {d["day"]: d["pnl"] for d in db.daily_pnl()}
    curve = {c["day"]: c["balance"] for c in db.equity_curve(ACCOUNT_BASELINE)}

    sigs = db.signals_for_month(year, month)
    sig_by_day: dict[int, list] = {}
    for s in sigs:
        d = date.fromtimestamp(s["received_at"]) if s["received_at"] else None
        if d and d.year == year and d.month == month:
            sig_by_day.setdefault(d.day, []).append(s)

    cells = []
    month_pnl = 0.0
    for i in range(first_wd):
        cells.append({"dim": True})
    for day in range(1, num_days + 1):
        iso = f"{year:04d}-{month:02d}-{day:02d}"
        pnl = round(float(daily.get(iso, 0.0)), 2)
        month_pnl += pnl
        is_today = today == date(year, month, day)
        cells.append({
            "day": day,
            "iso": iso,
            "pnl": pnl,
            "balance": curve.get(iso),
            "trading": iso in daily,
            "today": is_today,
            "sigs": sig_by_day.get(day, [])[:3],
        })

    def _nav(delta: int):
        m = month + delta
        y = year
        if m < 1:
            m, y = 12, year - 1
        elif m > 12:
            m, y = 1, year + 1
        return y, m

    return {
        "year": year,
        "month": month,
        "next": _nav(1),
        "prev": _nav(-1),
        "cells": cells,
        "month_name": pycal.month_name[month],
        "month_pnl": round(month_pnl, 2),
        "num_trading_days": sum(1 for c in cells if c.get("trading")),
        "signals_count": len(sigs),
    }


def _account_live():
    try:
        import MetaTrader5 as mt5

        from core import autotrade
        if not autotrade._ready():
            return None
        acc = mt5.account_info()
        if not acc:
            return None
        return {
            "balance": round(float(acc.balance), 2),
            "equity": round(float(acc.equity), 2),
            "free_margin": round(float(acc.margin_free), 2),
            "margin": round(float(acc.margin), 2),
            "positions": len(mt5.positions_get() or []),
        }
    except Exception:
        return None


@app.route("/")
def index():
    try:
        year = int(request.args.get("year", date.today().year))
        month = int(request.args.get("month", date.today().month))
    except ValueError:
        year, month = date.today().year, date.today().month
    view = _calendar_view(year, month)
    s = db.stats()
    curve = db.equity_curve(ACCOUNT_BASELINE)
    wins = s["wins"] or 0
    losses = s["losses"] or 0
    win_rate = round(wins / (wins + losses) * 100, 1) if (wins + losses) else 0.0

    chart = {
        "labels": [c["day"][5:] for c in curve],
        "values": [c["balance"] for c in curve],
        "baseline": ACCOUNT_BASELINE,
    }

    return render_template(
        "index.html",
        active_nav="calendar",
        mode=_mode(),
        account=MT5_ACCOUNT or "—",
        autotrade=AUTOTRADE_ENABLED,
        view=view,
        stats=s,
        win_rate=win_rate,
        chart=chart,
        total_pnl=s["pnl"],
        last_balance=curve[-1]["balance"] if curve else ACCOUNT_BASELINE,
    )


@app.route("/trades")
def trades_page():
    return render_template(
        "trades.html",
        active_nav="trades",
        mode=_mode(),
        account=MT5_ACCOUNT or "—",
        autotrade=AUTOTRADE_ENABLED,
        total_pnl=db.stats()["pnl"],
    )


@app.route("/api/calendar")
def api_calendar():
    year = int(request.args.get("year", date.today().year))
    month = int(request.args.get("month", date.today().month))
    return jsonify(_calendar_view(year, month))


@app.route("/api/trades")
def api_trades():
    limit = int(request.args.get("limit", "100"))
    return jsonify(db.recent_trades(limit))


@app.route("/api/grouped")
def api_grouped():
    limit = int(request.args.get("limit", "50"))
    return jsonify(db.grouped_trades(limit))


@app.route("/api/stats")
def api_stats():
    return jsonify(db.stats())


@app.route("/api/account")
def api_account():
    live = _account_live()
    if live is None:
        curve = db.equity_curve(ACCOUNT_BASELINE)
        live = {"balance": curve[-1]["balance"] if curve else ACCOUNT_BASELINE,
                "equity": None, "free_margin": None, "margin": None,
                "positions": None, "stale": True}
    return jsonify(live)


if __name__ == "__main__":
    print("SignalPilot dashboard on http://127.0.0.1:5001")
    app.run(host="127.0.0.1", port=5001, debug=False)