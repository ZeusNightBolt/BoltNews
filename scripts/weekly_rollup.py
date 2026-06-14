#!/usr/bin/env python3.12
"""
BoltNews — Weekly Rollup.

Aggregates the actual BoltNews briefing artifacts for the week. The primary
source is daily temporal_brief.md when it exists; otherwise fall back to each
run's briefing.md, then summary.md. Article metadata is loaded from
articles_enriched.json when available, otherwise articles.json.
"""
import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from textwrap import shorten

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_ROOT / "runs"
WEEKLY_DIR = PROJECT_ROOT / "weekly"

BRIEFING_MARKERS = ("Executive Summary", "Cross-Asset", "Positioning", "Contrarian")
RUN_MODES = ("pre-market", "post-market")
WEEKEND_RUN_MODES = ("weekend",)


def parse_date(value: str | None) -> date:
    return date.fromisoformat(value) if value else date.today()


def get_week_dates(asof: date) -> list[str]:
    """Get week dates containing *asof*.

    Friday rollups keep the legacy Monday-Friday window. If the rollup is run
    on Saturday/Sunday, include weekend dates so weekend briefings are not dead
    code for weekly aggregation/debug runs.
    """
    monday = asof - timedelta(days=asof.weekday())
    days = 7 if asof.weekday() >= 5 else 5
    return [(monday + timedelta(days=i)).isoformat() for i in range(days)]


def read_text(path: Path) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(errors="replace").strip()
    return text or None


def markdown_quality(text: str | None) -> str:
    if not text:
        return "missing"
    if any(marker.lower() in text.lower() for marker in BRIEFING_MARKERS):
        return "briefing"
    if len(text) >= 5_000:
        return "long-form"
    return "digest"


def load_run_markdown(run_date: str, mode: str) -> dict | None:
    """Load the best markdown context for one run.

    Historical bug: weekly_rollup.py only looked at summary.md, while recent
    runs write the research note to briefing.md and reserve summary.md for a
    short article digest/link index. This function makes briefing.md primary.
    """
    run_dir = RUNS_DIR / run_date / mode
    candidates = ["briefing.md", "summary.md", "articles.md"]
    for filename in candidates:
        path = run_dir / filename
        text = read_text(path)
        if text:
            return {
                "date": run_date,
                "mode": mode,
                "path": path,
                "filename": filename,
                "text": text,
                "quality": markdown_quality(text),
                "chars": len(text),
            }
    return None


def load_daily_temporal(run_date: str) -> dict | None:
    path = RUNS_DIR / run_date / "daily" / "temporal_brief.md"
    text = read_text(path)
    if not text:
        return None
    return {
        "date": run_date,
        "mode": "daily",
        "path": path,
        "filename": "temporal_brief.md",
        "text": text,
        "quality": "temporal",
        "chars": len(text),
    }


def normalize_articles(payload) -> list[dict]:
    if isinstance(payload, list):
        return [a for a in payload if isinstance(a, dict)]
    if isinstance(payload, dict):
        for key in ("articles", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [a for a in value if isinstance(a, dict)]
    return []


def load_articles(run_date: str, mode: str) -> tuple[list[dict], str | None]:
    """Load article metadata. Use articles_enriched.json if present, else articles.json."""
    run_dir = RUNS_DIR / run_date / mode
    for filename in ("articles_enriched.json", "articles.json"):
        path = run_dir / filename
        if not path.exists():
            continue
        try:
            articles = normalize_articles(json.loads(path.read_text(errors="replace")))
        except Exception:
            articles = []
        return articles, filename
    return [], None


def collect_week_context(week_dates: list[str]) -> tuple[list[dict], list[dict], list[dict]]:
    contexts: list[dict] = []
    run_stats: list[dict] = []
    all_articles: list[dict] = []

    for d in week_dates:
        temporal = load_daily_temporal(d)
        if temporal:
            contexts.append(temporal)
        modes = WEEKEND_RUN_MODES if date.fromisoformat(d).weekday() >= 5 else RUN_MODES
        for mode in modes:
            run_context = load_run_markdown(d, mode)
            articles, article_source = load_articles(d, mode)
            all_articles.extend(articles)
            run_stats.append({
                "date": d,
                "mode": mode,
                "markdown": run_context["filename"] if run_context else None,
                "markdown_quality": run_context["quality"] if run_context else "missing",
                "markdown_chars": run_context["chars"] if run_context else 0,
                "articles_source": article_source,
                "article_count": len(articles),
            })
            # Include run-level briefing contexts too. Temporal briefs are a daily diff;
            # run briefings retain the complete AM/PM research note.
            if run_context:
                contexts.append(run_context)

    return contexts, run_stats, all_articles


def excerpt_markdown(text: str, max_chars: int = 1200) -> str:
    """Return a compact markdown excerpt preserving section headings."""
    cleaned = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(cleaned) <= max_chars:
        return cleaned
    # Prefer Executive Summary / opening section if present.
    match = re.search(r"(?is)(#{1,3}\s*Executive Summary.*?)(?:\n#{1,3}\s+|\Z)", cleaned)
    if match and len(match.group(1)) >= 250:
        return shorten(re.sub(r"\s+", " ", match.group(1)), width=max_chars, placeholder=" …")
    return shorten(re.sub(r"\s+", " ", cleaned), width=max_chars, placeholder=" …")


def article_title(article: dict) -> str:
    return str(article.get("title") or article.get("headline") or "Untitled").strip()


def article_description(article: dict) -> str:
    return str(article.get("description") or article.get("summary") or article.get("snippet") or "").strip()


def article_category(article: dict) -> str:
    return str(article.get("category") or article.get("asset_class") or "Equities").strip() or "Equities"


def build_weekly_summary(week_dates: list[str], asof: date | None = None) -> str:
    """Build the weekly rollup markdown from real briefing artifacts."""
    asof = asof or date.today()
    week_start = date.fromisoformat(week_dates[0])
    week_end = date.fromisoformat(week_dates[-1])
    contexts, run_stats, all_articles = collect_week_context(week_dates)

    days_with_context = sorted({c["date"] for c in contexts})
    source_counter = Counter(c["filename"] for c in contexts)

    lines = [
        "# BoltNews — Weekly Rollup",
        f"**{week_start.isoformat()} → {week_end.isoformat()}**",
        f"*Generated: {asof.isoformat()}*",
        "",
        "---",
        "",
        "## 📊 Coverage Audit",
        "",
        f"**Days covered by markdown context:** {len(days_with_context)} / {len(week_dates)} ({', '.join(days_with_context)})",
        f"**Run markdown contexts loaded:** {len(contexts)}",
        f"**Total article metadata records:** {len(all_articles)}",
        "**Markdown source mix:** " + (", ".join(f"{k}: {v}" for k, v in sorted(source_counter.items())) or "none"),
        "",
        "| Date | Run | Markdown source | Quality | Chars | Article source | Articles |",
        "|---|---|---:|---|---:|---:|---:|",
    ]
    for stat in run_stats:
        mode_label = "🌅 AM" if stat["mode"] == "pre-market" else "🌆 PM"
        lines.append(
            f"| {stat['date']} | {mode_label} | {stat['markdown'] or 'MISSING'} | "
            f"{stat['markdown_quality']} | {stat['markdown_chars']} | "
            f"{stat['articles_source'] or 'MISSING'} | {stat['article_count']} |"
        )

    missing = [s for s in run_stats if not s["markdown"]]
    if missing:
        lines += ["", "### ⚠️ Missing run markdown", ""]
        for s in missing:
            lines.append(f"- {s['date']} {s['mode']}: no briefing.md, summary.md, or articles.md found")

    lines += ["", "## 🗓️ Daily Briefing Context", ""]
    by_date: dict[str, list[dict]] = defaultdict(list)
    for ctx in contexts:
        by_date[ctx["date"]].append(ctx)
    for d in week_dates:
        lines.append(f"### {d}")
        day_contexts = by_date.get(d, [])
        if not day_contexts:
            lines.append("*No markdown context found for this date.*")
            lines.append("")
            continue
        # Show temporal first, then AM, then PM, then weekend.
        order = {"daily": 0, "pre-market": 1, "post-market": 2, "weekend": 3}
        for ctx in sorted(day_contexts, key=lambda c: order.get(c["mode"], 99)):
            label = {
                "daily": "Temporal reasoning",
                "pre-market": "Pre-market",
                "post-market": "Post-market",
                "weekend": "Weekend",
            }.get(ctx["mode"], ctx["mode"])
            rel = ctx["path"].relative_to(PROJECT_ROOT)
            lines.append(f"#### {label} — `{rel}` ({ctx['quality']}, {ctx['chars']} chars)")
            lines.append("")
            lines.append(excerpt_markdown(ctx["text"], 1100))
            lines.append("")

    if all_articles:
        lines += ["## 🔥 Top Stories by Category", ""]
        by_category: dict[str, list[dict]] = defaultdict(list)
        seen_urls: set[str] = set()
        for article in all_articles:
            url = str(article.get("url") or "").strip()
            key = url or article_title(article)
            if key in seen_urls:
                continue
            seen_urls.add(key)
            by_category[article_category(article)].append(article)
        sorted_cats = sorted(by_category.items(), key=lambda x: len(x[1]), reverse=True)
        for cat, cat_articles in sorted_cats[:7]:
            lines.append(f"### {cat} ({len(cat_articles)} articles)")
            lines.append("")
            cat_articles.sort(key=lambda a: len(article_description(a)), reverse=True)
            for article in cat_articles[:8]:
                ticker = f"`{article.get('ticker')}` " if article.get("ticker") else ""
                title = article_title(article)
                url = str(article.get("url") or "").strip()
                desc = article_description(article)
                if url:
                    lines.append(f"- {ticker}[{title}]({url})")
                else:
                    lines.append(f"- {ticker}{title}")
                if desc:
                    lines.append(f"  - {shorten(desc, width=240, placeholder=' …')}")
            lines.append("")

    lines += ["## 🧵 Key Themes This Week", ""]
    all_text = " ".join(
        [c["text"] for c in contexts]
        + [article_title(a) + " " + article_description(a) for a in all_articles]
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
    theme_counts = {
        kw: len(re.findall(r"\b" + re.escape(kw) + r"\b", all_text))
        for kw in theme_keywords
    }
    theme_counts = {k: v for k, v in theme_counts.items() if v >= 3}
    if theme_counts:
        for kw, count in sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)[:15]:
            lines.append(f"- **{kw.title()}**: mentioned {count} times")
    else:
        lines.append("*No dominant themes detected.*")

    lines += [
        "",
        "---",
        "*Generated by BoltNews Weekly Rollup. Source priority: daily/temporal_brief.md → run briefing.md → run summary.md → articles.md; article metadata: articles_enriched.json → articles.json.*",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="BoltNews Weekly Rollup")
    parser.add_argument("--date", type=str, default=None, help="Anchor date for week selection, YYYY-MM-DD; default today")
    parser.add_argument("--output", type=Path, default=None, help="Output path (default: weekly/YYYY-MM-DD.md)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    asof = parse_date(args.date)
    week_dates = get_week_dates(asof)
    print(f"Week of {week_dates[0]} → {week_dates[-1]}")

    if args.dry_run:
        contexts, run_stats, all_articles = collect_week_context(week_dates)
        print(f"  contexts: {len(contexts)}")
        print(f"  articles: {len(all_articles)}")
        for stat in run_stats:
            status = "✓" if stat["markdown"] else "✗"
            print(
                f"  {stat['date']} {stat['mode']}: {status} "
                f"markdown={stat['markdown'] or 'MISSING'} quality={stat['markdown_quality']} "
                f"chars={stat['markdown_chars']} articles={stat['article_count']} source={stat['articles_source'] or 'MISSING'}"
            )
        return

    summary = build_weekly_summary(week_dates, asof=asof)
    output_path = args.output or (WEEKLY_DIR / f"{week_dates[-1]}.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(summary)

    print(f"Weekly rollup: {output_path}")
    print(f"  {len(summary)} chars")


if __name__ == "__main__":
    main()
