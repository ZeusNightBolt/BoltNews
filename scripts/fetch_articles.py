#!/usr/bin/env python3.12
"""
BoltNews — Article Fetcher.
Uses web_search + web_extract to find recent news for tickers and market topics.
Outputs structured articles.json with headline, lead paragraph, source, timestamp.
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, date
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from html.parser import HTMLParser

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# Ticker batch size — search in groups to stay within rate limits
TICKER_BATCH_SIZE = 5
# Generic topic batch size
TOPIC_BATCH_SIZE = 2
# Delay between batches (seconds)
BATCH_DELAY = 2
# Max articles per ticker
MAX_PER_TICKER = 3
# Max articles per topic
MAX_PER_TOPIC = 5

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


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def is_market_relevant(text: str) -> bool:
    """Check if text is market-relevant (not blocked, has signal)."""
    text_lower = text.lower()
    # Block list
    for kw in BLOCKED_KEYWORDS:
        if kw in text_lower:
            return False
    # Signal check
    for kw in SIGNAL_KEYWORDS:
        if kw.lower() in text_lower:
            return True
    # If it mentions ticker, money, markets — keep it
    if any(w in text_lower for w in ["$", "stock", "share", "bond", "yield", "rate", "market"]):
        return True
    return False


def search_ticker_news(ticker: str, search_date: str) -> list[dict]:
    """Search for recent news about a ticker using web_search tool."""
    # This is called from the agent context — uses web_search tool
    # When run standalone, uses subprocess to call hermes web search
    # For cron execution, the agent itself performs these searches
    queries = [
        f"{ticker} stock news {search_date}",
        f"{ticker} earnings report news",
        f"{ticker} analyst upgrade downgrade",
    ]
    articles = []
    for query in queries[:2]:  # Limit to 2 queries per ticker
        try:
            results = _do_web_search(query, limit=3)
            for r in results:
                if is_market_relevant(r.get("title", "") + " " + r.get("description", "")):
                    articles.append({
                        "ticker": ticker,
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "description": r.get("description", ""),
                        "source": "web_search",
                        "query": query,
                    })
        except Exception as e:
            print(f"  WARN: search failed for {ticker}: {e}", file=sys.stderr)
        time.sleep(1)
    return articles[:MAX_PER_TICKER]


def search_topic_news(topic: str, search_date: str) -> list[dict]:
    """Search for market-wide news on a topic."""
    queries = [
        f"{topic} news {search_date}",
        f"{topic} market impact {search_date}",
    ]
    articles = []
    for query in queries[:1]:
        try:
            results = _do_web_search(query, limit=5)
            for r in results:
                if is_market_relevant(r.get("title", "") + " " + r.get("description", "")):
                    articles.append({
                        "ticker": None,
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "description": r.get("description", ""),
                        "source": "web_search",
                        "query": query,
                        "topic": topic,
                    })
        except Exception as e:
            print(f"  WARN: search failed for topic '{topic}': {e}", file=sys.stderr)
        time.sleep(1)
    return articles[:MAX_PER_TOPIC]


def _do_web_search(query: str, limit: int = 5) -> list[dict]:
    """
    Perform web search. When running as a cron job agent, the agent
    itself calls web_search tool. This module provides the query builder.
    
    When run standalone for testing, it generates the query plan.
    """
    # In agent context: web_search(query, limit) returns results
    # In standalone: return empty (queries are consumed by the agent)
    return []  # Stub — agent fills this in during execution


def generate_search_plan(universe: dict, mode: str) -> dict:
    """Generate the search plan for the agent to execute."""
    tickers = [t["ticker"] for t in universe["tickers"]]
    topics = universe.get("market_topics", [])
    
    # Prioritize tickers with upcoming earnings, high short interest, or high vol
    prioritized = sorted(
        universe["tickers"],
        key=lambda t: (
            t.get("has_upcoming_earnings", False),
            t.get("short_pct_float", 0) or 0,
            t.get("annualized_vol", 0) or 0,
        ),
        reverse=True,
    )[:50]  # Focus on top 50 highest-signal tickers
    
    plan = {
        "mode": mode,
        "generated": datetime.now().isoformat(),
        "total_tickers": len(tickers),
        "prioritized_tickers": [t["ticker"] for t in prioritized],
        "topics": topics[:15],  # Top 15 market topics
        "search_queries": [],
    }
    
    # Build ticker queries
    for t in prioritized:
        plan["search_queries"].append({
            "type": "ticker",
            "ticker": t["ticker"],
            "name": t["name"],
            "queries": [
                f"{t['ticker']} stock news",
                f"{t['ticker']} {t.get('industry', '')} news",
            ],
        })
    
    # Build topic queries
    for topic in topics[:15]:
        plan["search_queries"].append({
            "type": "topic",
            "topic": topic,
            "queries": [f"{topic} news today"],
        })
    
    return plan


def main():
    parser = argparse.ArgumentParser(description="BoltNews Article Fetcher")
    parser.add_argument("--mode", choices=["pre-market", "post-market"], required=True)
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--date", type=str, required=True)
    parser.add_argument("--plan-only", action="store_true", help="Generate search plan, don't search")
    args = parser.parse_args()
    
    universe = load_json(args.universe)
    
    if args.plan_only:
        plan = generate_search_plan(universe, args.mode)
        with open(args.output, "w") as f:
            json.dump(plan, f, indent=2, default=str)
        print(f"Search plan saved to {args.output}")
        print(f"  Prioritized tickers: {len(plan['prioritized_tickers'])}")
        print(f"  Topics: {len(plan['topics'])}")
        print(f"  Total queries: {len(plan['search_queries'])}")
        return
    
    # Generate plan and save as article placeholders
    plan = generate_search_plan(universe, args.mode)
    
    # In cron/agent mode, the articles are populated by the agent.
    # Save the plan as the output — agent enriches it with actual results.
    output = {
        "mode": args.mode,
        "date": args.date,
        "generated": datetime.now().isoformat(),
        "plan": plan,
        "articles": [],  # Populated by agent during cron execution
        "stats": {
            "tickers_searched": 0,
            "topics_searched": 0,
            "articles_found": 0,
            "articles_filtered": 0,
        },
    }
    
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2, default=str)
    
    print(f"Article fetch plan saved to {args.output}")
    print(f"  Ready for agent execution: {len(plan['search_queries'])} searches queued")


if __name__ == "__main__":
    main()
