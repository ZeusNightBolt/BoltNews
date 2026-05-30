#!/usr/bin/env python3.12
"""
BoltNews — Ticker Universe Builder.
Pulls VTI holdings from DuckDB → filters >$5B market cap → ranks by dollar volume → takes top 15%.
Outputs universe.json with tickers + metadata for news search targeting.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = Path.home() / "market-data" / "market_data.duckdb"

# Filters
MIN_MARKET_CAP = 5_000_000_000  # $5B
TOP_PCT = 0.15  # top 15% by dollar volume
MIN_COUNT = 50  # floor — never return fewer than this many tickers


def build_universe(output_path: Path | None = None) -> dict:
    """Build filtered universe from DuckDB VTI enriched data."""
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)

    # Query: filter by market cap, rank by dollar volume
    query = """
    SELECT
        ticker,
        holding_name AS name,
        market_cap,
        dollar_volume,
        close AS price,
        volume,
        yf_sector,
        yf_industry,
        sic_description,
        market_cap_rank,
        dollar_volume AS dollar_volume_rank_source,
        has_upcoming_earnings,
        short_pct_float,
        volatility_annual_polygon AS annualized_vol
    FROM vti_daily_enriched_latest
    WHERE market_cap >= ?
      AND dollar_volume > 0
      AND ticker IS NOT NULL
    ORDER BY dollar_volume DESC
    """

    rows = con.execute(query, [MIN_MARKET_CAP]).fetchall()
    columns = [d[0] for d in con.description]
    con.close()

    if not rows:
        print("ERROR: No tickers matched filter criteria.", file=sys.stderr)
        sys.exit(1)

    # Take top 15% by dollar volume, floor at MIN_COUNT
    cutoff = max(MIN_COUNT, int(len(rows) * TOP_PCT))
    selected = rows[:cutoff]

    universe = []
    for row in selected:
        d = dict(zip(columns, row))
        universe.append({
            "ticker": d["ticker"],
            "name": d["name"],
            "market_cap": d["market_cap"],
            "dollar_volume": d["dollar_volume"],
            "price": d["price"],
            "volume": d["volume"],
            "sector": d["yf_sector"],
            "industry": d["yf_industry"],
            "sic_description": d["sic_description"],
            "has_upcoming_earnings": d["has_upcoming_earnings"],
            "short_pct_float": d["short_pct_float"],
            "annualized_vol": d["annualized_vol"],
        })

    # Add generic market topics for broad searches
    market_topics = [
        "S&P 500", "NASDAQ", "Dow Jones", "Russell 2000",
        "Federal Reserve", "FOMC", "interest rates", "Treasury yields",
        "US dollar", "DXY", "forex", "currency markets",
        "credit markets", "corporate bonds", "investment grade", "high yield",
        "oil prices", "crude oil", "natural gas", "commodities",
        "stock market", "equity markets", "volatility", "VIX",
        "options market", "derivatives", "futures market",
    ]

    result = {
        "generated": datetime.now().isoformat(),
        "source": "vti_daily_enriched_latest",
        "total_vti_tickers": len(rows),
        "selected_count": len(universe),
        "filters": {
            "min_market_cap": MIN_MARKET_CAP,
            "top_pct_by_dollar_volume": TOP_PCT,
            "floor_count": MIN_COUNT,
        },
        "tickers": universe,
        "market_topics": market_topics,
    }

    output_path = output_path or (DATA_DIR / "universe.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(f"Universe built: {len(universe)} tickers (from {len(rows)} >${MIN_MARKET_CAP/1e9:.0f}B MCap)")
    print(f"Top ticker: {universe[0]['ticker']} (${universe[0]['dollar_volume']:,.0f} daily dollar vol)")
    print(f"Bottom ticker: {universe[-1]['ticker']} (${universe[-1]['dollar_volume']:,.0f} daily dollar vol)")
    print(f"Saved to: {output_path}")

    return result


if __name__ == "__main__":
    build_universe()
