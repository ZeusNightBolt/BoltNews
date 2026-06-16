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
from zoneinfo import ZoneInfo
from session_logic import session_window

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


MODE_BRIEFING_SECTIONS = {
    "pre-market": [
        "Futures and Current Market Snapshot",
        "Overnight Top Developments",
        "Global Session Recap",
        "Macro, Rates, and Policy Setup",
        "FX and Commodities",
        "Equities and Single-Stock Watchlist",
        "Sector and Factor Setup",
        "Today's Risk Map",
        "Source Notes and Data Quality",
    ],
    "post-market": [
        "Closing Market Snapshot",
        "Why Markets Moved",
        "Equity Market Internals",
        "Rates, Macro, and Policy",
        "Earnings and Corporate Developments",
        "Cross-Asset Confirmation or Divergence",
        "Tomorrow Setup",
        "Source Notes and Data Quality",
    ],
    "weekend": [
        "Weekly Market Scoreboard",
        "The Week's Core Narrative",
        "Macro and Policy Review",
        "Equity and Sector Review",
        "Commodities, FX, Credit, and Volatility",
        "Geopolitics and Event Risk",
        "Next Week Playbook",
        "Historical Context",
        "Source Notes and Data Quality",
    ],
}

WEEKDAY_TOPIC_PACKS = {
    "Monday": {
        "pre-market": ["Monday premarket futures", "week ahead stocks", "economic calendar this week", "Fed speakers this week", "Treasury yields Monday", "earnings this week", "analyst upgrades downgrades Monday", "oil prices Monday", "dollar index Monday", "China markets overnight"],
        "post-market": ["Monday market close", "stocks start week", "after hours earnings Monday", "guidance raised lowered Monday", "Treasury auction reaction", "Fed official comments Monday", "sector rotation Monday"],
    },
    "Tuesday": {
        "pre-market": ["Tuesday premarket futures", "global markets overnight", "earnings before the bell Tuesday", "analyst ratings Tuesday", "Treasury yields Tuesday", "retail sales CPI PPI preview"],
        "post-market": ["Tuesday market close", "earnings after hours Tuesday", "semiconductor earnings Tuesday", "mega cap results Tuesday", "Fed comments Tuesday", "commodity market reaction Tuesday"],
    },
    "Wednesday": {
        "pre-market": ["Wednesday premarket futures", "FOMC minutes preview", "mortgage applications housing data", "crude oil inventory preview", "earnings before bell Wednesday", "AI chip stock news Wednesday"],
        "post-market": ["Wednesday market close", "FOMC minutes market reaction", "crude inventories oil prices", "earnings after hours Wednesday", "Nasdaq reaction Wednesday", "rates FX credit Wednesday"],
    },
    "Thursday": {
        "pre-market": ["Thursday premarket futures", "jobless claims preview", "ECB BOE central bank decision", "earnings before bell Thursday", "retail earnings Thursday", "Treasury yields Thursday"],
        "post-market": ["Thursday market close", "jobless claims market reaction", "earnings after hours Thursday", "guidance cut raised Thursday", "dollar yields Thursday", "credit spreads Thursday"],
    },
    "Friday": {
        "pre-market": ["Friday premarket futures", "payrolls jobs report preview", "PCE inflation preview", "options expiration Friday", "earnings before bell Friday", "week ending market setup"],
        "post-market": ["Friday market close", "weekly stock market wrap", "S&P 500 Nasdaq weekly performance", "options expiration market impact", "fund flows week", "week ahead market outlook"],
    },
}

WEEKEND_TOPICS = [
    "Wall Street week ahead", "earnings week ahead", "economic data next week", "Fed week ahead",
    "global macro outlook", "stock market weekly recap", "Barron's markets", "investor sentiment survey",
    "hedge fund positioning", "credit markets outlook", "currency markets outlook", "oil gold commodities outlook",
    "AI semiconductor outlook", "consumer stocks outlook", "bank stocks outlook",
]

AGENT_LANE_CONFIG = [
    {"lane": "market-snapshot", "agents": 1, "lane_timeout_seconds": 300, "search_timeout_seconds": 45, "extract_timeout_seconds": 60, "max_articles": 12},
    {"lane": "overnight-or-session-headlines", "agents": 1, "lane_timeout_seconds": 420, "search_timeout_seconds": 45, "extract_timeout_seconds": 75, "max_articles": 20},
    {"lane": "macro-policy-rates-fx", "agents": 1, "lane_timeout_seconds": 420, "search_timeout_seconds": 45, "extract_timeout_seconds": 75, "max_articles": 20},
    {"lane": "equities-earnings-single-stocks", "agents": 2, "lane_timeout_seconds": 480, "search_timeout_seconds": 45, "extract_timeout_seconds": 75, "max_articles": 35},
    {"lane": "commodities-credit-vol", "agents": 1, "lane_timeout_seconds": 360, "search_timeout_seconds": 45, "extract_timeout_seconds": 75, "max_articles": 20},
    {"lane": "dedupe-validation-synthesis", "agents": 1, "lane_timeout_seconds": 300, "requires_all_discovery_outputs": True},
]

LANE_SECTION_MAP = {
    "market-snapshot": ["Futures and Current Market Snapshot", "Closing Market Snapshot", "Weekly Market Scoreboard"],
    "overnight-or-session-headlines": ["Overnight Top Developments", "Global Session Recap", "Why Markets Moved", "The Week's Core Narrative"],
    "macro-policy-rates-fx": ["Macro, Rates, and Policy Setup", "Rates, Macro, and Policy", "Macro and Policy Review", "FX and Commodities"],
    "equities-earnings-single-stocks": ["Equities and Single-Stock Watchlist", "Sector and Factor Setup", "Equity Market Internals", "Earnings and Corporate Developments", "Equity and Sector Review"],
    "commodities-credit-vol": ["FX and Commodities", "Commodities, FX, Credit, and Volatility", "Cross-Asset Confirmation or Divergence"],
    "dedupe-validation-synthesis": ["Source Notes and Data Quality"],
}


def recency_window(target_date: str, mode: str) -> dict:
    """Return a Wall-Street-calendar/session-aware recency window."""
    return session_window(target_date, mode)

def topic_keyword_pack(weekday: str, mode: str, universe_topics: list[str]) -> dict:
    """Return mode + weekday specific topic keywords for the run."""
    if mode == "weekend":
        topics = WEEKEND_TOPICS
    else:
        topics = WEEKDAY_TOPIC_PACKS.get(weekday, {}).get(mode, [])
        if universe_topics:
            topics = topics + [t for t in universe_topics if t not in topics]
        topics = topics[:18]
    return {
        "pack_id": f"{weekday.lower()}-{mode}",
        "weekday": weekday,
        "mode": mode,
        "primary_topics": topics[:10],
        "secondary_topics": topics[10:],
        "exclusion_terms": BLOCKED_KEYWORDS,
        "query_templates": [
            "{topic} {date_suffix}",
            "{topic} markets today {date_suffix}",
            "{topic} Reuters Bloomberg CNBC {date_suffix}",
            "{topic} stocks bonds yields {date_suffix}",
        ],
    }


def build_agent_lanes(mode: str, topic_pack: dict, prioritized: list[dict]) -> list[dict]:
    """Build self-contained multi-agent lane assignments for search/extract execution."""
    ticker_symbols = [t["ticker"] for t in prioritized]
    lanes = []
    for cfg in AGENT_LANE_CONFIG:
        lane = dict(cfg)
        lane["assigned_sections"] = [s for s in LANE_SECTION_MAP.get(lane["lane"], []) if s in MODE_BRIEFING_SECTIONS[mode] or s == "Source Notes and Data Quality"]
        if lane["lane"] == "equities-earnings-single-stocks":
            lane["assigned_tickers"] = ticker_symbols
            lane["assigned_topics"] = ["earnings", "guidance", "analyst upgrades downgrades", "pre-market movers", "after-hours movers"]
        elif lane["lane"] == "market-snapshot":
            lane["assigned_topics"] = ["stock futures", "market close", "Treasury yields", "DXY", "WTI Brent oil", "gold", "VIX"]
        elif lane["lane"] == "overnight-or-session-headlines":
            lane["assigned_topics"] = topic_pack["primary_topics"][:8]
        elif lane["lane"] == "macro-policy-rates-fx":
            lane["assigned_topics"] = [t for t in topic_pack["primary_topics"] + topic_pack["secondary_topics"] if any(k in t.lower() for k in ["fed", "treasury", "yield", "cpi", "ppi", "payroll", "pce", "dollar", "fx", "economic", "central bank"])]
        elif lane["lane"] == "commodities-credit-vol":
            lane["assigned_topics"] = [t for t in topic_pack["primary_topics"] + topic_pack["secondary_topics"] if any(k in t.lower() for k in ["oil", "gold", "commodity", "credit", "vol", "vix", "options"])]
        else:
            lane["assigned_topics"] = []
        lanes.append(lane)
    return lanes


def ticker_expected_sections(mode: str) -> list[str]:
    """Return mode-valid sections for ticker and single-stock article assignments."""
    if mode == "pre-market":
        return ["Equities and Single-Stock Watchlist", "Sector and Factor Setup"]
    if mode == "post-market":
        return ["Earnings and Corporate Developments", "Equity Market Internals"]
    return ["Equity and Sector Review"]


def verification_gates(mode: str) -> list[dict]:
    return [
        {"gate": "schema", "require": ["mode", "date", "date_suffix", "recency_hours", "generated", "articles", "stats"]},
        {"gate": "timestamp", "rule": "Each article needs parseable published_at inside the recency window unless explicitly typed market_data."},
        {"gate": "freshness", "rule": "Reject stale indicators unless clearly historical context from BoltNews archives."},
        {"gate": "extraction", "rule": "Reject headline-only records; require lead paragraph or extracted_text/body snippet."},
        {"gate": "relevance", "rule": "Require explicit market impact, signal keywords, or direct macro/asset relevance."},
        {"gate": "dedupe", "rule": "Dedupe on canonical URL, normalized URL, and normalized headline/source pair."},
        {"gate": "coverage", "rule": f"briefing.md must include required sections for {mode}: " + ", ".join(MODE_BRIEFING_SECTIONS[mode])},
        {"gate": "dashboard", "rule": "Rendered dashboard TOC anchors must resolve and internal links must not 404."},
    ]


def handoff_prompt_template() -> str:
    return (
        "You are a BoltNews article discovery subagent.\n"
        "Mode: {mode}\nTarget date: {target_date}\nWeekday: {weekday}\n"
        "Recency window: {window_start_iso} to {window_end_iso} ({timezone})\n"
        "Lane: {lane}\nAssigned section(s): {sections}\nAssigned search items: {items}\n"
        "Query templates: {query_templates}\n"
        "Timeouts: search={search_timeout_seconds}s, extraction={extract_timeout_seconds}s, lane={lane_timeout_seconds}s\n\n"
        "Rules:\n"
        "1. Accept only articles published inside the Wall Street session window, not merely the calendar day.\n"
        "2. Every accepted article requires title/headline, url, source, published_at, fetched_at, tickers/topics, assigned_section, summary/lead paragraph, and extracted_text/body excerpt.\n"
        "3. Reject missing timestamps unless the record is explicitly live market_data for the market snapshot. For post-market, reject articles before the 9:30 AM ET cash open.\n"
        "4. Reject stale, evergreen, quote-page, and headline-only records.\n"
        "5. Do not web-search historical context; use prior BoltNews markdown artifacts only.\n"
        "6. Prefer Reuters/Bloomberg/WSJ/CNBC/MarketWatch/Yahoo/official releases/central banks/exchanges/regulators.\n"
        "7. Return JSON only using the lane output schema.\n"
    )


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

    weekday = datetime.fromisoformat(target_date).strftime("%A")
    if is_weekend:
        prioritized = sorted(
            universe["tickers"],
            key=lambda t: (t.get("market_cap", 0) or 0),
            reverse=True,
        )[:25]
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
    topic_pack = topic_keyword_pack(weekday, mode, topics)
    run_recency = recency_window(target_date, mode)
    run_lanes = build_agent_lanes(mode, topic_pack, prioritized)

    plan = {
        "schema_version": "2.0",
        "mode": mode,
        "weekday": weekday,
        "weekday_index": datetime.fromisoformat(target_date).weekday(),
        "is_weekend": is_weekend,
        "target_date": target_date,
        "date_suffix": date_suffix,
        "recency_hours": run_recency["hours"],
        "recency": run_recency,
        "source_policy": {
            "preferred_sources": ["Reuters", "Bloomberg", "WSJ", "CNBC", "MarketWatch", "Yahoo Finance", "official releases", "central banks", "exchanges", "regulators"],
            "allowed_source_classes": ["newswire", "market_data", "official", "central_bank", "company_release", "rates", "fx", "commodities", "credit", "analysis"],
            "restricted_source_classes": ["forum", "social"],
            "paywall_policy": "Extract if accessible; never invent text behind a paywall.",
            "historical_context_policy": "Use prior BoltNews markdown artifacts only; do not web-search stale context.",
        },
        "briefing_template": {
            "required_sections": MODE_BRIEFING_SECTIONS[mode],
            "authoritative_output": "briefing.md",
            "summary_md_policy": "article digest/link index only; never primary dashboard content",
        },
        "topic_keyword_pack": topic_pack,
        "agent_execution": {
            "global_timeout_seconds": 1800,
            "max_parallel_agents": 6,
            "search_timeout_seconds": 45,
            "extract_timeout_seconds": 75,
            "searxng_backoff_seconds": [3, 8, 20],
            "max_retries_per_query": 2,
            "dedupe_keys": ["canonical_url", "normalized_headline", "source"],
        },
        "lanes": run_lanes,
        "verification_gates": verification_gates(mode),
        "handoff_prompt_template": handoff_prompt_template(),
        "recency_warning": (
            f"AGENT INSTRUCTION: Only accept articles published within the past "
            f"{run_recency['hours']} hours (window starts {run_recency['window_start_iso']}). "
            f"All search queries include '{date_suffix}' to enforce recency. "
            f"DO NOT include articles outside that trading-session window, including prior-day rally articles in a post-market recap. Historical context "
            f"is stored in markdown dumps — this pipeline is for NEW content only."
        ),
        "generated": datetime.now().isoformat(),
        "total_tickers": len(tickers),
        "prioritized_tickers": [t["ticker"] for t in prioritized],
        "topics": topic_pack["primary_topics"] + topic_pack["secondary_topics"],
        "search_queries": [],
    }

    # Build ticker queries — ALL suffixed with the target date
    for t in prioritized:
        ticker = t["ticker"]
        industry = t.get("industry", "")
        
        if is_weekend:
            plan["search_queries"].append({
                "id": f"ticker-{ticker.lower()}",
                "type": "ticker",
                "lane": "equities-earnings-single-stocks",
                "priority": 1,
                "expected_sections": ticker_expected_sections(mode),
                "ticker": ticker,
                "name": t["name"],
                "queries": [
                    f"{ticker} stock news {date_suffix}",
                    f"{ticker} {industry} analysis {date_suffix}" if industry else f"{ticker} analysis {date_suffix}",
                    f"{ticker} stock outlook investor focus {date_suffix}",
                ],
                "max_results": MAX_PER_TICKER,
                "timeout_seconds": 45,
                "requires_extraction": True,
                "freshness_required": True,
            })
        else:
            plan["search_queries"].append({
                "id": f"ticker-{ticker.lower()}",
                "type": "ticker",
                "lane": "equities-earnings-single-stocks",
                "priority": 1,
                "expected_sections": ticker_expected_sections(mode),
                "ticker": ticker,
                "name": t["name"],
                "queries": [
                    f"{ticker} stock news today {date_suffix}",
                    f"{ticker} {industry} news {date_suffix}" if industry else f"{ticker} news {date_suffix}",
                    f"{ticker} earnings guidance analyst rating {date_suffix}",
                    f"{ticker} shares premarket after hours {date_suffix}",
                ],
                "max_results": MAX_PER_TICKER,
                "timeout_seconds": 45,
                "requires_extraction": True,
                "freshness_required": True,
            })

    # Build topic queries — ALL suffixed with the target date
    for idx, topic in enumerate(topic_pack["primary_topics"] + topic_pack["secondary_topics"], start=1):
        lane = "market-snapshot" if idx == 1 else "overnight-or-session-headlines"
        if any(k in topic.lower() for k in ["fed", "treasury", "yield", "cpi", "ppi", "payroll", "pce", "dollar", "fx", "economic", "central bank"]):
            lane = "macro-policy-rates-fx"
        elif any(k in topic.lower() for k in ["oil", "gold", "commodity", "credit", "vol", "vix", "options"]):
            lane = "commodities-credit-vol"
        elif any(k in topic.lower() for k in ["earnings", "stock", "sector", "analyst", "semiconductor", "consumer", "bank"]):
            lane = "equities-earnings-single-stocks"
        plan["search_queries"].append({
            "id": f"topic-{idx:03d}",
            "type": "topic",
            "topic": topic,
            "lane": lane,
            "priority": 1 if idx <= len(topic_pack["primary_topics"]) else 2,
            "expected_sections": [s for s in LANE_SECTION_MAP.get(lane, []) if s in MODE_BRIEFING_SECTIONS[mode]],
            "queries": [template.format(topic=topic, date_suffix=date_suffix) for template in topic_pack["query_templates"]],
            "expected_source_classes": ["newswire", "market_data", "official", "analysis"],
            "max_results": MAX_PER_TOPIC,
            "timeout_seconds": 45,
            "requires_extraction": True,
            "freshness_required": True,
            "article_acceptance": {
                "require_published_at": True,
                "max_age_hours": run_recency["hours"],
                "window_start_iso": run_recency["window_start_iso"],
                "window_end_iso": run_recency["window_end_iso"],
                "require_market_relevance": True,
                "reject_summary_only": True,
            },
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
        "recency_hours": plan["recency_hours"],
        "recency": plan["recency"],
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
