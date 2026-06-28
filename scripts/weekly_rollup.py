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
    """Build the weekly rollup markdown from real briefing artifacts.

    Keep the output headings aligned with docs/briefing-template-spec.md and the
    weekly cron prompt. Earlier versions emitted audit/debug headings, which made
    successful script runs produce non-compliant weekly artifacts.
    """
    asof = asof or date.today()
    week_start = date.fromisoformat(week_dates[0])
    week_end = date.fromisoformat(week_dates[-1])
    contexts, run_stats, all_articles = collect_week_context(week_dates)

    days_with_context = sorted({c["date"] for c in contexts})
    source_counter = Counter(c["filename"] for c in contexts)
    all_text = " ".join(
        [c["text"] for c in contexts]
        + [article_title(a) + " " + article_description(a) for a in all_articles]
    ).lower()

    def keyword_count(words: list[str]) -> int:
        return sum(len(re.findall(r"\b" + re.escape(word) + r"\b", all_text)) for word in words)

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
    missing = [s for s in run_stats if not s["markdown"]]
    best_contexts = sorted(contexts, key=lambda c: (c["quality"] != "temporal", -c["chars"]))[:6]

    lines = [
        "# BoltNews — Weekly Rollup",
        f"**{week_start.isoformat()} → {week_end.isoformat()}**",
        f"*Generated: {asof.isoformat()}*",
        "",
        "## Weekly Market Scoreboard",
        "",
        f"- **Coverage:** {len(days_with_context)} / {len(week_dates)} dates with markdown context ({', '.join(days_with_context) or 'none'}).",
        f"- **Inputs:** {len(contexts)} markdown contexts and {len(all_articles)} article metadata records.",
        "- **Source mix:** " + (", ".join(f"{k}: {v}" for k, v in sorted(source_counter.items())) or "none"),
        "",
        "| Date | Run | Markdown source | Quality | Chars | Article source | Articles |",
        "|---|---|---:|---|---:|---:|---:|",
    ]
    for stat in run_stats:
        mode_label = {"pre-market": "AM", "post-market": "PM", "weekend": "Weekend"}.get(stat["mode"], stat["mode"])
        lines.append(
            f"| {stat['date']} | {mode_label} | {stat['markdown'] or 'MISSING'} | "
            f"{stat['markdown_quality']} | {stat['markdown_chars']} | "
            f"{stat['articles_source'] or 'MISSING'} | {stat['article_count']} |"
        )

    lines += ["", "## Dominant Cross-Asset Narrative", ""]
    if best_contexts:
        for ctx in best_contexts:
            rel = ctx["path"].relative_to(PROJECT_ROOT)
            lines.append(f"### {ctx['date']} {ctx['mode']} — `{rel}`")
            lines.append(excerpt_markdown(ctx["text"], 900))
            lines.append("")
    else:
        lines.append("Data unavailable — no weekly briefing context found.")

    lines += ["## Asset Class Deep Dive", ""]
    if sorted_cats:
        for cat, cat_articles in sorted_cats[:7]:
            lines.append(f"### {cat} ({len(cat_articles)} articles)")
            cat_articles.sort(key=lambda a: len(article_description(a)), reverse=True)
            for article in cat_articles[:5]:
                ticker = f"`{article.get('ticker')}` " if article.get("ticker") else ""
                title = article_title(article)
                url = str(article.get("url") or "").strip()
                desc = article_description(article)
                lines.append(f"- {ticker}[{title}]({url})" if url else f"- {ticker}{title}")
                if desc:
                    lines.append(f"  - {shorten(desc, width=220, placeholder=' …')}")
            lines.append("")
    else:
        lines.append("Data unavailable — no article metadata found.")

    lines += ["## Positioning, Sentiment, and Flows", ""]
    theme_groups = {
        "rates/policy": ["rate", "cut", "hike", "fed", "fomc", "yield"],
        "inflation/macro": ["inflation", "cpi", "ppi", "payroll", "gdp"],
        "earnings/corporates": ["earnings", "revenue", "guidance", "upgrade", "downgrade"],
        "volatility/risk": ["volatility", "vix", "sell-off", "rally", "correction"],
        "commodities": ["oil", "energy", "commodity", "gold", "copper"],
        "credit/banks": ["bank", "credit", "default", "spread"],
        "AI/semis/tech": ["ai", "chip", "semiconductor", "tech"],
    }
    counts = {name: keyword_count(words) for name, words in theme_groups.items()}
    for name, count in sorted(counts.items(), key=lambda x: x[1], reverse=True):
        if count:
            lines.append(f"- **{name}:** {count} mentions across loaded weekly context.")
    if not any(counts.values()):
        lines.append("Data unavailable — no dominant positioning/sentiment keywords detected.")

    lines += ["", "## Earnings, Guidance, and Corporate Actions", ""]
    corp_articles = [a for a in all_articles if re.search(r"earnings|revenue|guidance|upgrade|downgrade|merger|acquisition|buyback", article_title(a) + " " + article_description(a), re.I)]
    for article in corp_articles[:10]:
        url = str(article.get("url") or "").strip()
        title = article_title(article)
        lines.append(f"- [{title}]({url})" if url else f"- {title}")
    if not corp_articles:
        lines.append("Data unavailable — no tagged earnings/corporate-action article metadata found.")

    lines += ["", "## Macro and Policy Outlook", ""]
    macro_hits = [name for name in ("rates/policy", "inflation/macro", "commodities", "credit/banks") if counts.get(name)]
    lines.append("- Macro theme intensity: " + (", ".join(f"{name}={counts[name]}" for name in macro_hits) if macro_hits else "Data unavailable — no macro keyword concentration detected."))

    lines += ["", "## Next Week Calendar and Watchlist", ""]
    lines.append("- Use the next pre-market run to refresh event timing and consensus figures; this deterministic rollup does not fabricate forward calendar items absent from source briefings.")
    for ctx in best_contexts[:3]:
        if "calendar" in ctx["text"].lower() or "watch" in ctx["text"].lower():
            lines.append(f"- Watchlist context from {ctx['date']} {ctx['mode']}: `{ctx['path'].relative_to(PROJECT_ROOT)}`")

    lines += ["", "## Contrarian Flags and Underpriced Risks", ""]
    risk_terms = {"contrarian": keyword_count(["contrarian"]), "risk": keyword_count(["risk"]), "divergence": keyword_count(["divergence"]), "volatility": keyword_count(["volatility", "vix"])}
    for name, count in sorted(risk_terms.items(), key=lambda x: x[1], reverse=True):
        if count:
            lines.append(f"- **{name}:** {count} mentions; review source excerpts above for context before acting.")
    if not any(risk_terms.values()):
        lines.append("Data unavailable — no explicit contrarian/risk markers detected.")

    lines += ["", "## Source Notes and Data Quality", ""]
    if missing:
        lines.append("### Missing run markdown")
        for s in missing:
            lines.append(f"- {s['date']} {s['mode']}: no briefing.md, summary.md, or articles.md found")
    else:
        lines.append("- All expected run slots had markdown context for the selected week window.")
    lines.append("- Source priority: daily/temporal_brief.md → run briefing.md → run summary.md → articles.md; article metadata: articles_enriched.json → articles.json.")
    lines.append("- This script aggregates and excerpts verified artifacts; final PM synthesis should preserve source/timestamp caveats from the underlying briefings.")

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
