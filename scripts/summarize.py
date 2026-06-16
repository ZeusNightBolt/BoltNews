#!/usr/bin/env python3.12
"""
BoltNews — Summarizer + Deduplicator with RECENCY ENFORCEMENT.
Filters articles >48 hours old BEFORE deduplication/categorization.
Articles 24-48h: accepted with age flag. Articles >48h: REJECTED.
Context/historical references: moved to a separate section, not mixed with news.
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, date
from pathlib import Path

from session_logic import article_in_window, session_window

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# === RECENCY GATES ===
MAX_NEWS_HOURS = 48  # Legacy hard cutoff; session_window is stricter for weekday runs
STALE_WARN_HOURS = 24  # Articles older than this get a [24h+] age flag

# Stale indicators — comprehensive patterns that signal >48h content
STALE_PATTERNS = [
    r"\blast\s+(?:week|month|quarter|year)\b",
    r"\b(?:january|february|march|april)\s+2026\b",
    r"\b(?:may\s+(?:1[0-9]|2[0-7])\b)",  # Early May dates (adjust for run date)
    r"\b2025\b",
    r"\b2024\b",
    r"\bQ[12]\s*2026\b",
    r"\bH1\s*2026\b",
    r"\b(?:months|weeks)\s+ago\b",
    r"\b(?:january|february)\s*(?:20)?25\b",
    r"\bDecember\s*2025\b",
    r"\b(?:last|earlier\s+this)\s+(?:year|quarter)\b",
    r"\bmid-2025\b",
    r"\blate\s+2025\b",
    r"\bfirst\s+half\b",
]

CATEGORIES = {
    "Rates": ["fed", "fomc", "interest rate", "treasury", "yield", "bond", "sofr", "libor",
              "central bank", "ecb", "boj", "boe", "monetary policy", "inflation", "cpi", "ppi"],
    "FX": ["forex", "currency", "dollar", "euro", "yen", "sterling", "yuan", "dxy", "usd",
           "fx", "exchange rate", "devaluation", "intervention"],
    "Credit": ["credit", "corporate bond", "high yield", "investment grade", "cds", "spread",
               "default", "distressed", "leveraged loan", "clo", "debt", "refinancing"],
    "Equities": ["stock", "equity", "share", "earnings", "revenue", "guidance", "dividend",
                 "buyback", "ipo", "index", "nasdaq", "dow", "s&p", "russell", "sector"],
    "Derivatives": ["option", "future", "derivative", "vix", "volatility", "hedge", "swap",
                    "gamma", "delta", "structured product", "etf", "etn"],
    "Macro": ["gdp", "payroll", "unemployment", "pmi", "ism", "consumer", "housing", "retail",
              "trade", "tariff", "geopolitical", "oil", "commodity", "energy", "recession"],
    "Regulatory": ["sec", "cftc", "doj", "antitrust", "regulation", "compliance", "fine",
                   "lawsuit", "litigation", "settlement", "probe", "investigation"],
}

BLOCKED_CATEGORIES = {
    "ESG/Social": ["esg", "climate", "carbon", "sustainability", "diversity", "inclusion",
                   "social", "activism", "protest", "gender", "racial", "equality"],
}


def load_articles(path: Path) -> list[dict]:
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    articles = data.get("articles", [])
    # Guard against a search-plan frame being accidentally passed as articles.json.
    # Plan frames contain search_queries/recency_warning and either no articles key
    # or an empty articles list. Treat that as a pipeline error, not as a valid
    # zero-article news day, because it produces empty dashboards.
    if (
        isinstance(data, dict)
        and not articles
        and ("search_queries" in data or "recency_warning" in data or "prioritized_tickers" in data)
    ):
        raise ValueError(
            f"{path} is a search plan, not an article feed. "
            "Populate articles.json with extracted articles before summarizing."
        )
    return articles


def is_article_stale(article: dict, max_hours: int, run_date_str: str) -> tuple[bool, float | None]:
    """
    Check if an article is stale. Returns (is_stale: bool, age_hours: float | None).
    
    Checks in order:
    1. Explicit fetched_at or published timestamp
    2. Stale text patterns in title/description
    """
    run_date = datetime.fromisoformat(run_date_str)
    
    # Method 1: Explicit timestamp
    for ts_field in ["fetched_at", "published_at", "date", "timestamp"]:
        ts_str = article.get(ts_field, "")
        if ts_str:
            try:
                ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00")[:19])
                age_hours = (run_date - ts.replace(tzinfo=None)).total_seconds() / 3600
                return age_hours > max_hours, age_hours
            except (ValueError, TypeError):
                continue
    
    # Method 2: Text pattern matching
    text = (article.get("title", "") + " " + article.get("description", "")).lower()
    for pattern in STALE_PATTERNS:
        if re.search(pattern, text):
            return True, None  # Pattern match = stale, unknown exact age
    
    # Method 3: No evidence of staleness → accept with unknown age
    return False, None


def session_filter_article(article: dict, mode: str, run_date_str: str) -> tuple[bool, str, float | None]:
    """Return whether an article belongs to the Wall Street session window."""
    window = session_window(run_date_str, mode)
    ok, reason, age_hours = article_in_window(article, window)
    if not ok:
        return False, reason, age_hours
    text = (article.get("title", "") + " " + article.get("description", "")).lower()
    for pattern in STALE_PATTERNS:
        if re.search(pattern, text):
            return False, "stale_text_pattern", age_hours
    return True, reason, age_hours


def categorize_article(article: dict) -> str:
    text = (article.get("title", "") + " " + article.get("description", "")).lower()
    for cat, keywords in BLOCKED_CATEGORIES.items():
        if any(kw in text for kw in keywords):
            return None
    scores = defaultdict(int)
    for cat, keywords in CATEGORIES.items():
        scores[cat] = sum(1 for kw in keywords if kw in text)
    if max(scores.values()) == 0:
        return "Equities"
    return max(scores, key=scores.get)


def compute_similarity(a: dict, b: dict) -> float:
    def tokens(article):
        text = (article.get("title", "") + " " + article.get("description", "")).lower()
        return set(re.findall(r'\b[a-z]{4,}\b', text))
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    intersection = ta & tb
    union = ta | tb
    return len(intersection) / len(union) if union else 0.0


def deduplicate(articles: list[dict], threshold: float = 0.35) -> list[dict]:
    if not articles:
        return []
    kept = []
    clusters = []
    for article in articles:
        matched = False
        for cluster in clusters:
            if compute_similarity(article, cluster[0]) >= threshold:
                cluster.append(article)
                matched = True
                break
        if not matched:
            clusters.append([article])
    for cluster in clusters:
        if len(cluster) == 1:
            kept.append(cluster[0])
        else:
            cluster.sort(key=lambda a: len(a.get("description", "")), reverse=True)
            kept.append(cluster[0])
            for other in cluster[1:]:
                if compute_similarity(cluster[0], other) < 0.6 and compute_similarity(cluster[0], other) >= threshold:
                    kept.append(other)
                    break
    return kept


def generate_one_liner(article: dict) -> str:
    title = article.get("title", "").strip()
    desc = article.get("description", "").strip()
    title = re.sub(r'\s+[-|]\s+.*$', '', title).rstrip('.')
    if not desc:
        return title
    first_sent = re.split(r'[.!?]\s+', desc)[0].strip()
    if len(first_sent) < 30:
        first_sent = desc[:200].strip()
    combined = f"{title} — {first_sent}"
    if len(combined) > 250:
        combined = combined[:247] + "..."
    return combined


def build_summary_markdown(articles: list[dict], context_articles: list[dict],
                           stale_stats: dict, mode: str, run_date: str) -> str:
    """Build the markdown briefing with recency flags."""
    if mode == "weekend":
        mode_label = "Weekend Briefing — Analysis & Outlook"
    elif mode == "pre-market":
        mode_label = "Pre-Market Briefing"
    else:
        mode_label = "Post-Market Recap"

    news_count = len(articles)
    context_count = len(context_articles)
    total_rejected = stale_stats.get("rejected", 0)

    lines = [
        f"# BoltNews — {mode_label}",
        f"**{run_date}** | {news_count} articles (≤{MAX_NEWS_HOURS}h) "
        + (f"| {context_count} context refs" if context_count else "")
        + (f" | {total_rejected} rejected (>48h)" if total_rejected else ""),
        "",
    ]

    # News articles
    by_category = defaultdict(list)
    for article in articles:
        cat = article.get("category", categorize_article(article))
        if cat is None:
            continue
        article["category"] = cat
        by_category[cat].append(article)

    sorted_cats = sorted(by_category.items(), key=lambda x: len(x[1]), reverse=True)

    for cat, cat_articles in sorted_cats:
        lines.append(f"## {cat}")
        lines.append("")
        for a in cat_articles:
            ticker_tag = f"`{a['ticker']}` " if a.get("ticker") else ""
            one_liner = a.get("summary", generate_one_liner(a))
            url = a.get("url", "")
            age_hours = a.get("age_hours")
            age_flag = ""
            if age_hours is not None and age_hours > STALE_WARN_HOURS:
                age_flag = f" ⏱ [{age_hours:.0f}h ago]"
            if url:
                lines.append(f"- {ticker_tag}[{one_liner}]({url}){age_flag}")
            else:
                lines.append(f"- {ticker_tag}{one_liner}{age_flag}")
        lines.append("")

    # Context section (articles rejected for staleness but kept for reference)
    if context_articles:
        lines.append("---")
        lines.append("## 📚 Historical Context (reference only — NOT current news)")
        lines.append("")
        lines.append(f"*The following {context_count} sources are >{MAX_NEWS_HOURS}h old and included ONLY as background context.*")
        lines.append("*They are NOT part of today's news digest. Use the daily summary dumps for historical tracking.*")
        lines.append("")
        for a in context_articles:
            ticker_tag = f"`{a['ticker']}` " if a.get("ticker") else ""
            title = a.get("title", "Untitled")
            url = a.get("url", "")
            age_hours = a.get("age_hours", "?")
            if url:
                lines.append(f"- {ticker_tag}[{title}]({url}) — ~{age_hours}h old")
            else:
                lines.append(f"- {ticker_tag}{title} — ~{age_hours}h old")
        lines.append("")

    # Stats footer
    lines.append("---")
    lines.append(f"*Generated by BoltNews • {news_count} articles (≤{MAX_NEWS_HOURS}h) "
                 + f"• {len(sorted_cats)} categories • "
                 + f"{total_rejected} stale articles rejected • "
                 + f"{context_count} kept as context*")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="BoltNews Summarizer")
    parser.add_argument("--input", type=Path, required=True, help="articles.json input")
    parser.add_argument("--output", type=Path, required=True, help="summary.md output")
    parser.add_argument("--mode", choices=["pre-market", "post-market", "weekend"], required=True)
    parser.add_argument("--date", type=str, required=True)
    parser.add_argument("--max-hours", type=int, default=MAX_NEWS_HOURS,
                        help=f"Max article age in hours (default: {MAX_NEWS_HOURS})")
    args = parser.parse_args()

    try:
        articles = load_articles(args.input)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    if not articles:
        print("ERROR: No articles to summarize; refusing to write an empty summary/dashboard feed.", file=sys.stderr)
        sys.exit(2)

    # ═══════════════════════════════════════════
    # RECENCY GATE — THE PROGRAMMATIC ENFORCEMENT
    # ═══════════════════════════════════════════
    fresh_articles = []
    context_articles = []  # >48h but kept as reference
    rejected_count = 0

    for a in articles:
        in_window, reason, age_hours = session_filter_article(a, args.mode, args.date)
        if not in_window:
            if a.get("title") or a.get("description"):
                a["rejected_reason"] = reason
                a["age_hours"] = age_hours
                context_articles.append(a)
            rejected_count += 1
        else:
            a["age_hours"] = age_hours
            a["session_window_status"] = reason
            fresh_articles.append(a)

    print(f"Session-window filter ({args.mode} {args.date}): "
          f"{len(articles)} → {len(fresh_articles)} inside window, "
          f"{len(context_articles)} context, {rejected_count} rejected")

    stale_stats = {
        "total_input": len(articles),
        "fresh": len(fresh_articles),
        "context": len(context_articles),
        "rejected": rejected_count,
    }

    # ═══════════════════════════════════════════
    # Deduplicate + Categorize + Summarize
    # ═══════════════════════════════════════════
    original_count = len(fresh_articles)
    fresh_articles = deduplicate(fresh_articles)
    print(f"Deduplication: {original_count} → {len(fresh_articles)} articles")

    for a in fresh_articles:
        a["category"] = categorize_article(a)
        a["summary"] = generate_one_liner(a)

    fresh_articles = [a for a in fresh_articles if a["category"] is not None]
    print(f"After category filtering: {len(fresh_articles)} articles")

    # Build markdown
    summary = build_summary_markdown(fresh_articles, context_articles, stale_stats,
                                     args.mode, args.date)

    with open(args.output, "w") as f:
        f.write(summary)

    # Save enriched articles
    enriched_path = args.input.parent / "articles_enriched.json"
    enriched_data = fresh_articles + context_articles
    for a in enriched_data:
        a.setdefault("age_hours", None)
        a.setdefault("rejected_reason", None)
    with open(enriched_path, "w") as f:
        json.dump(enriched_data, f, indent=2, default=str)

    print(f"Summary: {args.output}")
    print(f"Enriched articles: {enriched_path}")


if __name__ == "__main__":
    main()
