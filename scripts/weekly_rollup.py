#!/usr/bin/env python3.12
"""
BoltNews — Weekly Rollup.
Aggregates Mon-Fri daily summaries into a single weekly briefing.
Runs Friday at 8PM ET.
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_ROOT / "runs"
WEEKLY_DIR = PROJECT_ROOT / "weekly"


def get_week_dates() -> list[str]:
    """Get Monday-Friday dates for the current week."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return [(monday + timedelta(days=i)).isoformat() for i in range(5)]


def load_summary(run_date: str, mode: str) -> str | None:
    """Load a daily summary markdown file."""
    path = RUNS_DIR / run_date / mode / "summary.md"
    if path.exists():
        return path.read_text()
    return None


def load_articles(run_date: str, mode: str) -> list[dict]:
    """Load enriched articles from a daily run."""
    path = RUNS_DIR / run_date / mode / "articles_enriched.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


def build_weekly_summary(week_dates: list[str]) -> str:
    """Build the weekly rollup markdown."""
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=4)
    
    lines = [
        f"# BoltNews — Weekly Rollup",
        f"**{week_start.isoformat()} → {week_end.isoformat()}**",
        f"*Generated: {today.isoformat()}*",
        "",
        "---",
        "",
    ]
    
    all_articles = []
    daily_stats = []
    
    for d in week_dates:
        for mode in ["pre-market", "post-market"]:
            articles = load_articles(d, mode)
            summary = load_summary(d, mode)
            
            if articles or summary:
                all_articles.extend(articles)
                daily_stats.append({
                    "date": d,
                    "mode": mode,
                    "count": len(articles),
                    "has_summary": summary is not None,
                })
    
    # === Section 1: Week at a Glance ===
    lines.append("## 📊 Week at a Glance")
    lines.append("")
    lines.append(f"**Total articles:** {len(all_articles)}")
    lines.append(f"**Days covered:** {len(set(s['date'] for s in daily_stats))}")
    lines.append("")
    
    for stat in daily_stats:
        mode_label = "🌅 AM" if stat["mode"] == "pre-market" else "🌆 PM"
        status = "✓" if stat["has_summary"] else "✗ (no data)"
        lines.append(f"- **{stat['date']}** {mode_label}: {stat['count']} articles {status}")
    
    lines.append("")
    
    # === Section 2: Top Stories by Category ===
    if all_articles:
        lines.append("## 🔥 Top Stories by Category")
        lines.append("")
        
        by_category = defaultdict(list)
        for a in all_articles:
            cat = a.get("category", "Equities")
            by_category[cat].append(a)
        
        sorted_cats = sorted(by_category.items(), key=lambda x: len(x[1]), reverse=True)
        
        for cat, cat_articles in sorted_cats[:5]:  # Top 5 categories
            lines.append(f"### {cat} ({len(cat_articles)} articles)")
            lines.append("")
            # Show top 5 articles per category
            # Sort by description length as proxy for detail
            cat_articles.sort(key=lambda a: len(a.get("description", "")), reverse=True)
            for a in cat_articles[:5]:
                ticker = f"`{a['ticker']}` " if a.get("ticker") else ""
                title = a.get("title", "Untitled")
                url = a.get("url", "")
                if url:
                    lines.append(f"- {ticker}[{title}]({url})")
                else:
                    lines.append(f"- {ticker}{title}")
            lines.append("")
    
    # === Section 3: Key Themes ===
    lines.append("## 🧵 Key Themes This Week")
    lines.append("")
    
    # Extract recurring keywords
    all_text = " ".join(
        (a.get("title", "") + " " + a.get("description", ""))
        for a in all_articles
    ).lower()
    
    theme_keywords = [
        "rate", "cut", "hike", "inflation", "fed", "fomc",
        "earnings", "revenue", "guidance", "upgrade", "downgrade",
        "merger", "acquisition", "deal", "takeover",
        "volatility", "sell-off", "rally", "correction",
        "oil", "energy", "commodity", "supply",
        "tariff", "trade", "china", "geopolitical",
        "bank", "credit", "default", "spread",
        "ai", "chip", "semiconductor", "tech",
    ]
    
    theme_counts = {}
    for kw in theme_keywords:
        count = len(re.findall(r'\b' + re.escape(kw) + r'\b', all_text))
        if count >= 3:
            theme_counts[kw] = count
    
    if theme_counts:
        for kw, count in sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
            lines.append(f"- **{kw.title()}**: mentioned {count} times")
    else:
        lines.append("*No dominant themes detected.*")
    
    lines.append("")
    lines.append("---")
    lines.append(f"*Generated by BoltNews Weekly Rollup • {today.isoformat()}*")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="BoltNews Weekly Rollup")
    parser.add_argument("--output", type=Path, default=None, help="Output path (default: weekly/YYYY-MM-DD.md)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    
    week_dates = get_week_dates()
    print(f"Week of {week_dates[0]} → {week_dates[-1]}")
    
    if args.dry_run:
        for d in week_dates:
            for mode in ["pre-market", "post-market"]:
                summary = load_summary(d, mode)
                articles = load_articles(d, mode)
                status = "✓" if summary or articles else "✗"
                print(f"  {d} {mode}: {status} ({len(articles)} articles)")
        return
    
    summary = build_weekly_summary(week_dates)
    
    output_path = args.output or (WEEKLY_DIR / f"{week_dates[-1]}.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w") as f:
        f.write(summary)
    
    print(f"Weekly rollup: {output_path}")
    print(f"  {len(summary)} chars")


if __name__ == "__main__":
    main()
