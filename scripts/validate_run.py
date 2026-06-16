#!/usr/bin/env python3.12
"""BoltNews run artifact validator.

This is the deterministic guardrail between an LLM-assisted collection/synthesis
step and deployment. It fails closed when required artifacts are missing,
malformed, link-only, stale-plan-shaped, or section-incomplete.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

from session_logic import article_in_window, session_window

REQUIRED_SEARCH_PLAN_KEYS = {
    "schema_version",
    "recency",
    "briefing_template",
    "topic_keyword_pack",
    "agent_execution",
    "lanes",
    "verification_gates",
    "handoff_prompt_template",
}

REQUIRED_SECTIONS = {
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

PLAN_SHAPED_KEYS = {"search_queries", "prioritized_tickers", "recency_warning"}
CONTRADICTION_PHRASES = {
    "lower": [
        r"wall street closed higher",
        r"markets rallied today",
        r"market rallied today",
        r"s&p 500\s+\+",
        r"nasdaq\s+\+",
        r"technology led the rally",
        r"equities\s*↑",
        r"risk-on rotation",
        r"strong risk-on session",
    ],
    "higher": [
        r"markets sold off today",
        r"wall street closed lower",
        r"risk-off session",
    ],
}


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(errors="replace"))
    except FileNotFoundError:
        fail(f"missing required file: {path}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path}: {exc}")


def normalize_articles(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [a for a in payload if isinstance(a, dict)]
    if isinstance(payload, dict):
        if PLAN_SHAPED_KEYS & set(payload) and not payload.get("articles"):
            fail("articles.json is a search-plan-shaped payload, not an article feed")
        for key in ("articles", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [a for a in value if isinstance(a, dict)]
    fail("articles.json must be a list or a dict containing an articles/results/items list")
    return []


def heading_positions(markdown: str) -> dict[str, int]:
    positions: dict[str, int] = {}
    for match in re.finditer(r"^#{1,3}\s+(.+?)\s*$", markdown, re.MULTILINE):
        heading = re.sub(r"\s+", " ", match.group(1).strip())
        heading = heading.strip("# ")
        positions.setdefault(heading.lower(), match.start())
    return positions


def validate_sections(markdown: str, mode: str) -> None:
    required = REQUIRED_SECTIONS[mode]
    positions = heading_positions(markdown)
    missing = [h for h in required if h.lower() not in positions]
    if missing:
        fail(f"briefing.md missing required {mode} headings: {missing}")
    ordered = [positions[h.lower()] for h in required]
    if ordered != sorted(ordered):
        fail(f"briefing.md required {mode} headings are not in canonical order")


def validate_search_plan(path: Path, mode: str) -> None:
    data = load_json(path)
    if not isinstance(data, dict):
        fail("search_plan.json must be an object")
    missing = sorted(REQUIRED_SEARCH_PLAN_KEYS - set(data))
    if missing:
        fail(f"search_plan.json missing required keys: {missing}")
    template = data.get("briefing_template") or {}
    maybe_sections = None
    if isinstance(template, dict):
        maybe_sections = template.get("sections") or template.get("required_sections")
    if not isinstance(maybe_sections, list) or not maybe_sections:
        fail("search_plan.json briefing_template.sections must be a non-empty list")
    sections = maybe_sections
    expected = REQUIRED_SECTIONS[mode]
    section_names = [str(s.get("heading", s)) if isinstance(s, dict) else str(s) for s in sections]
    missing_sections = [h for h in expected if h not in section_names]
    if missing_sections:
        fail(f"search_plan.json template missing sections: {missing_sections}")
    lanes = data.get("lanes")
    if not isinstance(lanes, list) or len(lanes) < 5:
        fail("search_plan.json lanes must include the multi-agent lane plan")
    recency = data.get("recency") or {}
    if not isinstance(recency, dict):
        fail("search_plan.json recency must be an object")
    for key in ("window_start_iso", "window_end_iso", "timezone", "calendar"):
        if not recency.get(key):
            fail(f"search_plan.json recency missing session/calendar field: {key}")


def validate_articles(path: Path, min_articles: int, mode: str, run_date: str) -> list[dict[str, Any]]:
    articles = normalize_articles(load_json(path))
    if len(articles) < min_articles:
        fail(f"articles.json has {len(articles)} articles; minimum required is {min_articles}")
    bad = []
    outside = []
    window = session_window(run_date, mode)
    for i, a in enumerate(articles):
        title = str(a.get("title") or a.get("headline") or "").strip()
        url = str(a.get("url") or "").strip()
        body = str(a.get("extracted_text") or a.get("content") or a.get("description") or a.get("summary") or "").strip()
        if not title or not url or len(body) < 40:
            bad.append(i)
        if str(a.get("type") or "").lower() != "market_data":
            ok, reason, _age = article_in_window(a, window)
            if not ok:
                outside.append((i, reason, title[:80]))
    if bad:
        fail(f"articles.json contains {len(bad)} records missing title/url/substantive text; examples={bad[:5]}")
    if outside:
        fail(f"articles.json contains {len(outside)} records outside session window; examples={outside[:5]}")
    return articles


def validate_market_snapshot(path: Path, mode: str, run_date: str, briefing: str) -> None:
    if mode == "weekend":
        return
    data = load_json(path)
    if not isinstance(data, dict):
        fail("market_snapshot.json must be an object")
    if data.get("date") != run_date or data.get("mode") != mode:
        fail("market_snapshot.json date/mode does not match run")
    direction = str(data.get("market_direction") or "unknown").lower()
    if direction not in {"higher", "lower", "mixed"}:
        fail(f"market_snapshot.json has invalid market_direction: {direction}")
    symbols = data.get("symbols") or {}
    for required in ("sp500", "nasdaq", "dow"):
        row = symbols.get(required) or {}
        if not isinstance(row.get("pct_change"), (int, float)):
            fail(f"market_snapshot.json missing pct_change for {required}")
    text = briefing.lower()
    hits = [pat for pat in CONTRADICTION_PHRASES.get(direction, []) if re.search(pat, text)]
    if hits:
        fail(f"briefing.md contradicts market_snapshot direction={direction}; matched phrases={hits[:5]}")


def validate_dashboard(path: Path) -> None:
    if not path.exists() or path.stat().st_size < 5_000:
        fail(f"dashboard.html missing or too small: {path}")
    html = path.read_text(errors="replace")
    for marker in ("toc-card", "Source Articles"):
        if marker not in html:
            fail(f"dashboard.html missing marker: {marker}")
    if "Executive Summary" not in html and "Cross-Asset" not in html and "Weekly Market Scoreboard" not in html:
        fail("dashboard.html lacks synthesized briefing markers")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate BoltNews run artifacts before deploy/reporting success")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=sorted(REQUIRED_SECTIONS), required=True)
    parser.add_argument("--date", type=str, required=True)
    parser.add_argument("--min-articles", type=int, default=None)
    args = parser.parse_args()

    try:
        date.fromisoformat(args.date)
    except ValueError:
        fail(f"invalid --date: {args.date}")

    run_dir = args.run_dir
    if not run_dir.exists():
        fail(f"run directory does not exist: {run_dir}")

    min_articles = args.min_articles if args.min_articles is not None else (5 if args.mode == "weekend" else 8)

    validate_search_plan(run_dir / "search_plan.json", args.mode)
    articles = validate_articles(run_dir / "articles.json", min_articles, args.mode, args.date)

    briefing_path = run_dir / "briefing.md"
    if not briefing_path.exists() or briefing_path.stat().st_size < 2_000:
        fail(f"briefing.md missing or too small: {briefing_path}")
    briefing = briefing_path.read_text(errors="replace")
    validate_sections(briefing, args.mode)
    validate_market_snapshot(run_dir / "market_snapshot.json", args.mode, args.date, briefing)

    summary_path = run_dir / "summary.md"
    if not summary_path.exists() or summary_path.stat().st_size < 200:
        fail(f"summary.md missing or too small: {summary_path}")

    validate_dashboard(run_dir / "dashboard.html")

    print(
        f"OK: {args.mode} {args.date} validated: "
        f"{len(articles)} articles, briefing={briefing_path.stat().st_size} bytes"
    )


if __name__ == "__main__":
    main()
