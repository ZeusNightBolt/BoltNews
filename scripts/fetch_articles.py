#!/usr/bin/env python3.12
"""
BoltNews — Article Fetcher.
Uses web_search + web_extract to find recent news for tickers and market topics.
CRITICAL: ALL searches are constrained to the past 24 hours. Historical context 
comes from markdown dumps, not from re-searching stale data.

Outputs structured articles.json with headline, lead paragraph, source, fetched_at timestamp.
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# === RECENCY — THE CRITICAL CONSTRAINT ===
RECENCY_HOURS = 24  # NEVER pull articles older than this
# Date suffix appended to every query to force search engine recency
# Format: "May 31, 2026" — search engines respect date terms in queries

# === Search config ===
MAX_PER_TICKER = 3
MAX_PER_TOPIC = 5
BATCH_DELAY = 2

# Non-market keywords to filter OUT
BLOCKED_KEYWORDS = [
    "racism", "sexism", "discrimination", "diversity initiative", "DEI",
    "climate protest", "social justice", "inequality", "activist investor ESG",
    "labor strike", "union vote", "woke", "gender pay gap",
    "human rights", "refugee", "immigration ban", "abortion",
    "gun control", "police", "BLM", "LGBTQ", "transgender",
    "carbon neutral", "sustainability report", "ESG score",
]

# Market-relevant keywords to prioritize
SIGNAL_KEYWORDS = [
    "earnings", "revenue", "guidance", "upgrade", "downgrade",
    "acquisition", "merger", "buyout", "takeover", "spin-off",
    "restructuring", "layoff", "bankruptcy", "default",
    "rate hike", "rate cut", "FOMC", "inflation", "CPI", "PPI",
    "GDP", "payroll", "unemployment", "yield curve",
    "CEO", "CFO", "executive", "board", "activist",
    "FDA", "approval", "clinical trial", "patent",
    "supply chain", "chip", "semiconductor", "tariff",
    "share buyback", "dividend", "split", "IPO", "SPAC",
    "short squeeze", "gamma squeeze", "options flow",
]

# Stale-indicator keywords — if found in description, article is likely >24h old
STALE_INDICATORS = [
    "last week", "last month", "earlier this month", "earlier this year",
    "Q1 2026", "Q4 2025", "January 2026", "February 2026", "March 2026",
    "April 2026", "2025", "year-to-date", "YTD", 
]


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def format_date_suffix(target_date: str) -> str:
    """Convert '2026-05-31' → 'May 31, 2026' for search query suffix."""
    d = datetime.fromisoformat(target_date)
    return d.strftime("%B %d, %Y")  # "May 31, 2026"


def is_market_relevant(text: str) -> bool:
    """Check if text is market-relevant (not blocked, has signal)."""
    text_lower = text.lower()
    for kw in BLOCKED_KEYWORDS:
        if kw in text_lower:
            return False
    for kw in SIGNAL_KEYWORDS:
        if kw.lower() in text_lower:
            return True
    if any(w in text_lower for w in ["$", "stock", "share", "bond", "yield", "rate", "market"]):
        return True
    return False


def is_stale(text: str) -> bool:
    """Check if text references stale/old time periods."""
    text_lower = text.lower()
    for indicator in STALE_INDICATORS:
        if indicator.lower() in text_lower:
            return True
    return False


def generate_search_plan(universe: dict, mode: str, target_date: str) -> dict:
    """
    Generate search plan with 24-hour recency enforced.
    
    Every query includes the target date to force search engine recency filtering.
    The plan includes explicit instructions that results older than 24 hours
    MUST be discarded.
    """
    date_suffix = format_date_suffix(target_date)
    tickers = [t["ticker"] for t in universe["tickers"]]
    topics = universe.get("market_topics", [])
    is_weekend = mode == "weekend"

    if is_weekend:
        prioritized = sorted(
            universe["tickers"],
            key=lambda t: (t.get("market_cap", 0) or 0),
            reverse=True,
        )[:25]
        weekend_topics = [
            "stock market recap analysis",
            "markets outlook forecast",
            "federal reserve policy",
            "global macro outlook",
            "credit markets outlook",
            "currency markets analysis",
            "commodities outlook",
            "investing strategy",
            "hedge fund manager",
            "Barron's markets",
            "Wall Street week ahead",
            "earnings week ahead",
            "economic data next week",
            "investor sentiment survey",
            "markets weekend reading",
        ]
    else:
        prioritized = sorted(
            universe["tickers"],
            key=lambda t: (
                t.get("has_upcoming_earnings", False),
                t.get("short_pct_float", 0) or 0,
                t.get("annualized_vol", 0) or 0,
            ),
            reverse=True,
        )[:50]
        weekend_topics = topics[:15]

    plan = {
        "mode": mode,
        "is_weekend": is_weekend,
        "target_date": target_date,
        "date_suffix": date_suffix,
        "recency_hours": RECENCY_HOURS,
        "recency_warning": (
            f"AGENT INSTRUCTION: Only accept articles published within the past "
            f"{RECENCY_HOURS} hours (since ~{target_date}). "
            f"All search queries include '{date_suffix}' to enforce recency. "
            f"DO NOT include articles from earlier dates. Historical context "
            f"is stored in markdown dumps — this pipeline is for NEW content only."
        ),
        "generated": datetime.now().isoformat(),
        "total_tickers": len(tickers),
        "prioritized_tickers": [t["ticker"] for t in prioritized],
        "topics": weekend_topics,
        "search_queries": [],
    }

    # Build ticker queries — ALL suffixed with the target date
    for t in prioritized:
        ticker = t["ticker"]
        industry = t.get("industry", "")
        
        if is_weekend:
            plan["search_queries"].append({
                "type": "ticker",
                "ticker": ticker,
                "name": t["name"],
                "queries": [
                    f"{ticker} stock news {date_suffix}",
                    f"{ticker} {industry} analysis {date_suffix}" if industry else f"{ticker} analysis {date_suffix}",
                ],
            })
        else:
            plan["search_queries"].append({
                "type": "ticker",
                "ticker": ticker,
                "name": t["name"],
                "queries": [
                    f"{ticker} stock news today {date_suffix}",
                    f"{ticker} {industry} news {date_suffix}" if industry else f"{ticker} news {date_suffix}",
                ],
            })

    # Build topic queries — ALL suffixed with the target date
    for topic in weekend_topics:
        plan["search_queries"].append({
            "type": "topic",
            "topic": topic,
            "queries": [f"{topic} {date_suffix}"],
        })

    return plan


def main():
    parser = argparse.ArgumentParser(description="BoltNews Article Fetcher")
    parser.add_argument("--mode", choices=["pre-market", "post-market", "weekend"], required=True)
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--date", type=str, required=True,
                        help="Target date (YYYY-MM-DD). ALL queries constrained to this date's 24h window.")
    parser.add_argument("--plan-only", action="store_true",
                        help="Generate search plan, don't search")
    args = parser.parse_args()

    universe = load_json(args.universe)

    if args.plan_only:
        plan = generate_search_plan(universe, args.mode, args.date)
        with open(args.output, "w") as f:
            json.dump(plan, f, indent=2, default=str)
        print(f"Search plan saved to {args.output}")
        print(f"  Date constraint: {plan['date_suffix']} ({plan['recency_hours']}h window)")
        print(f"  Prioritized tickers: {len(plan['prioritized_tickers'])}")
        print(f"  Topics: {len(plan['topics'])}")
        print(f"  Total queries: {len(plan['search_queries'])}")
        return

    # Generate plan
    plan = generate_search_plan(universe, args.mode, args.date)

    output = {
        "mode": args.mode,
        "date": args.date,
        "date_suffix": plan["date_suffix"],
        "recency_hours": RECENCY_HOURS,
        "generated": datetime.now().isoformat(),
        "plan": plan,
        "articles": [],
        "stats": {
            "tickers_searched": 0,
            "topics_searched": 0,
            "articles_found": 0,
            "articles_filtered": 0,
            "articles_stale_rejected": 0,
        },
    }

    with open(args.output, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"Article fetch plan saved to {args.output}")
    print(f"  Date constraint: {plan['date_suffix']}")
    print(f"  Ready for agent execution: {len(plan['search_queries'])} searches queued")


if __name__ == "__main__":
    main()
