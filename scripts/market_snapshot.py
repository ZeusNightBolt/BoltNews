#!/usr/bin/env python3.12
"""Fetch deterministic market snapshot for BoltNews validation.

Uses Yahoo chart endpoints as a secondary market-data source because index quote
pages are publicly accessible and provide previous close + current/regular
market close.  If this fails, the pipeline should fail closed rather than let an
LLM invent market direction.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")

SYMBOLS = {
    "sp500": "%5EGSPC",
    "nasdaq": "%5EIXIC",
    "dow": "%5EDJI",
    "russell2000": "%5ERUT",
    "vix": "%5EVIX",
    "spy": "SPY",
    "qqq": "QQQ",
    "iwm": "IWM",
    "xle": "XLE",
    "xlk": "XLK",
}


def fetch_chart(symbol: str) -> dict:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=2d&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())
    result = (data.get("chart", {}).get("result") or [None])[0]
    if not result:
        raise RuntimeError(f"empty Yahoo chart result for {symbol}")
    meta = result.get("meta", {})
    quotes = (result.get("indicators", {}).get("quote") or [{}])[0]
    closes = [x for x in quotes.get("close", []) if x is not None]
    opens = [x for x in quotes.get("open", []) if x is not None]
    highs = [x for x in quotes.get("high", []) if x is not None]
    lows = [x for x in quotes.get("low", []) if x is not None]
    if not closes:
        raise RuntimeError(f"no close prices for {symbol}")
    latest = float(meta.get("regularMarketPrice") or closes[-1])
    prev = None
    if len(closes) >= 2:
        prev = float(closes[-2])
    elif meta.get("chartPreviousClose") is not None:
        prev = float(meta["chartPreviousClose"])
    if not prev:
        raise RuntimeError(f"no previous close for {symbol}")
    change = latest - prev
    pct = change / prev * 100
    return {
        "symbol": urllib.parse.unquote(symbol),
        "previous_close": round(prev, 4),
        "latest": round(latest, 4),
        "change": round(change, 4),
        "pct_change": round(pct, 4),
        "open": round(float(opens[-1]), 4) if opens else None,
        "high": round(float(highs[-1]), 4) if highs else None,
        "low": round(float(lows[-1]), 4) if lows else None,
        "regular_market_time": meta.get("regularMarketTime"),
        "currency": meta.get("currency"),
        "exchange": meta.get("exchangeName"),
    }


def classify(snapshot: dict) -> str:
    sp = snapshot["symbols"].get("sp500", {}).get("pct_change")
    ndx = snapshot["symbols"].get("nasdaq", {}).get("pct_change")
    dow = snapshot["symbols"].get("dow", {}).get("pct_change")
    vals = [x for x in (sp, ndx, dow) if isinstance(x, (int, float))]
    if len(vals) < 2:
        return "unknown"
    neg = sum(1 for x in vals if x < -0.05)
    pos = sum(1 for x in vals if x > 0.05)
    if neg >= 2:
        return "lower"
    if pos >= 2:
        return "higher"
    return "mixed"


def main() -> None:
    parser = argparse.ArgumentParser(description="Create BoltNews market_snapshot.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["pre-market", "post-market", "weekend"], required=True)
    parser.add_argument("--date", required=True)
    args = parser.parse_args()

    symbols = {}
    errors = {}
    for name, symbol in SYMBOLS.items():
        try:
            symbols[name] = fetch_chart(symbol)
        except Exception as exc:
            errors[name] = str(exc)
        time.sleep(0.2)

    if "sp500" not in symbols or "nasdaq" not in symbols:
        print(f"ERROR: missing required index quotes: {errors}", file=sys.stderr)
        raise SystemExit(2)

    snapshot = {
        "schema_version": "1.0",
        "source": "Yahoo Finance chart API (secondary source)",
        "generated_at": datetime.now(NY).isoformat(),
        "date": args.date,
        "mode": args.mode,
        "symbols": symbols,
        "errors": errors,
    }
    snapshot["market_direction"] = classify(snapshot)
    snapshot["must_not_claim"] = []
    if snapshot["market_direction"] == "lower":
        snapshot["must_not_claim"] = [
            "Wall Street closed higher",
            "strong risk-on session",
            "markets rallied today",
            "S&P 500 rallied",
            "Nasdaq rallied",
        ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=2))
    print(f"Market snapshot: {snapshot['market_direction']} -> {args.output}")
    for key in ("sp500", "nasdaq", "dow", "russell2000", "vix"):
        row = symbols.get(key)
        if row:
            print(f"  {key}: {row['latest']} ({row['pct_change']:+.2f}%)")


if __name__ == "__main__":
    main()
