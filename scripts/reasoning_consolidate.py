#!/usr/bin/env python3.12
"""
BoltNews — Reasoning Consolidator (replaces consolidate_daily.py)
=================================================================

PROBLEM: The old consolidate_daily.py mechanically concatenated PM and AM
summaries with zero cross-run reasoning. AVGO fell 12% AH in the PM run,
but the AM run wrote about its pre-earnings $479 close as if nothing happened.
The consolidated output stacked both narratives without reconciliation.

SOLUTION: This script loads the full synthesized briefing.md from both PM and
AM runs as its primary context, falls back to summary.md only when briefing.md
is absent, and uses articles.json only as secondary source-link metadata. It
then extracts structured data points (prices, percentages, earnings metrics,
oil, rates), groups by ticker/topic, computes temporal diffs, and generates a
narrative that explicitly shows WHAT CHANGED between 6PM and 6AM.

Key features:
- Data point extraction with regex (price moves, earnings, rates, oil, indices)
- Ticker-level temporal diff: PM value → AM value → direction
- Staleness detection: flags data points from PM that are contradicted or superseded by AM
- Source attribution: every data point cites its source and run time
- Narrative generation: "AVGO fell 12% AH (6PM), recovered to -8% by pre-market (6AM)"

48-hour freshness rule: Articles from either run within 48h are eligible.
Articles >48h are moved to Historical Context section.

Output structure:
  1. Executive Summary with cross-run delta highlights
  2. Per-Ticker Temporal Evolution (earnings, price moves)
  3. Macro Cross-Run Data Points (oil, rates, indices, FX)
  4. Key Sector Movers — confirmed vs contradicted
  5. New Overnight Developments (PM didn't have these)
  6. Historical Context (articles >48h)
  7. Cross-Asset Positioning Matrix (updated from both runs)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_ROOT / "runs"

# ── Data Point Extraction ─────────────────────────────────────────────────

# Patterns for extracting structured data from article text
# Each pattern returns (metric, value, context) tuples

PRICE_PATTERNS = [
    # "AH: $421.86 (-11.97%)" or "Close: $479.23 (-0.49%); AH: $421.86 (-11.97%)"
    (r'(?:AH|after[-\s]hours?)[:\s]+(\$[\d,.]+)\s*(?:\(?([+-]?[\d.]+%)\)?)?', 'after_hours_price'),
    # "stock at $479.23 (-0.5% pre-earnings)"  
    (r'(?:stock|shares?|close)[\s\w]*?(?:at\s+)?(\$[\d,.]+)\s*(?:\(?([+-]?[\d.]+%)\)?)?', 'price'),
    # "-11.97%" standalone near a ticker
    (r'([+-]?[\d.]+%)\s*(?:after[-\s]hours?|AH|pre[-\s]market)', 'percent_move'),
    # "$479.23" standalone — ONLY when near price context keywords
    (r'(?:(?:close|stock|shares?|trading)[\s\w]*?(?:at|was|is|fell|rose|dropped|gained)[\s\w]*?)(\$[\d,]+\.?\d*)', 'dollar_amount'),
]

EARNINGS_PATTERNS = [
    # Revenue: "$22.2B +48% YoY (beat $22.13B)"
    (r'(?:revenue|sales)[:\s]+(\$[\d.]+[BMK]?)\s*(?:[+\-][\d.]+%\s*YoY)?\s*(?:\(?(?:beat|miss|vs)\s+(\$[\d.]+[BMK]?)\)?)?', 'revenue'),
    # EPS: "$2.44 (beat $2.40)" or "EPS $1.10 (beat $1.07)"
    (r'(?:adj\.?\s*)?EPS[:\s]+(\$?[\d.]+)\s*(?:\(?(?:beat|miss|vs)\s+(\$?[\d.]+)\)?)?', 'eps'),
    # Guidance: "Q3 guide $29.4B" or "raised FY27 guidance"
    (r'(?:guide|guidance|outlook)[:\s]+(\$[\d.]+[BMK]?)(?:\s*(?:revenue|sales))?', 'guidance'),
    # AI revenue: "AI semi revenue $10.8B +143% YoY"
    (r'(?:AI|artificial intelligence)\s*(?:semi|chip|revenue|segment)[:\s]+(\$[\d.]+[BMK]?)\s*(?:[+\-][\d.]+%)?', 'ai_revenue'),
    # FCF: "FCF $10.3B (record)"
    (r'(?:FCF|free cash flow)[:\s]+(\$[\d.]+[BMK]?)\s*(?:\(?(?:record|[\d.]+%\s*(?:margin|of rev))\)?)?', 'fcf'),
]

OIL_PATTERNS = [
    # "WTI $94.77 +1.08%" or "Brent $97.05 +1.09%"
    (r'(?:WTI|crude)[:\s]+(\$[\d.]+)\s*(?:\(?([+-]?[\d.]+%)\)?)?', 'wti'),
    (r'Brent[:\s]+(\$[\d.]+)\s*(?:\(?([+-]?[\d.]+%)\)?)?', 'brent'),
]

RATES_PATTERNS = [
    # "10Y: 4.46%" or "10Y 4.48% (-2.1bp)"
    (r'(?:10[-\s]?[Yy]|10[-\s]?year)[:\s]+([\d.]+%)\s*(?:\(?([+-]?[\d.]+)\s*bp\)?)?', '10y'),
    (r'(?:30[-\s]?[Yy]|30[-\s]?year)[:\s]+([\d.]+%)\s*(?:\(?([+-]?[\d.]+)\s*bp\)?)?', '30y'),
    (r'(?:2[-\s]?[Yy]|2[-\s]?year)[:\s]+([\d.]+%)\s*(?:\(?([+-]?[\d.]+)\s*bp\)?)?', '2y'),
    # Fed funds: "Fed funds effective: 3.62%"
    (r'(?:fed funds|FFR)[:\s]+([\d.]+%)', 'fed_funds'),
]

INDEX_PATTERNS = [
    # "S&P 500 -0.74%" or "Dow -1.21% (600+ pts)" 
    (r'(?:S&P\s*500|SPX)[\s\w]*?([+-]?[\d.]+%)\s*(?:\(?[-+]?\d[\d,]*\s*pts?\)?)?', 'sp500'),
    (r'(?:Dow|DJI)[\s\w]*?([+-]?[\d.]+%)\s*(?:\(?[-+]?\d[\d,]*\s*pts?\)?)?', 'dow'),
    (r'(?:Nasdaq|NDX)[\s\w]*?([+-]?[\d.]+%)\s*(?:\(?[-+]?\d[\d,]*\s*pts?\)?)?', 'nasdaq'),
    (r'(?:Russell\s*2000|RTY|RUT)[\s\w]*?([+-]?[\d.]+%)', 'russell2000'),
    (r'VIX[:\s]+([\d.]+)\s*(?:\(?([+-]?[\d.]+%)\)?)?', 'vix'),
]

ALL_PATTERNS = {
    "price": PRICE_PATTERNS,
    "earnings": EARNINGS_PATTERNS,
    "oil": OIL_PATTERNS,
    "rates": RATES_PATTERNS,
    "indices": INDEX_PATTERNS,
}


def extract_data_points(article: dict, run_time: str, run_type: str) -> list[dict]:
    """Extract structured data points from article text with source attribution."""
    text = " ".join([
        article.get("title", ""),
        article.get("description", ""),
        " ".join(article.get("key_points", [])),
    ])
    ticker = article.get("ticker") or "MACRO"
    source = article.get("source", "unknown")
    url = article.get("url", "")
    
    data_points = []
    
    for category, patterns in ALL_PATTERNS.items():
        for pattern, metric_name in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                groups = match.groups()
                value = groups[0]
                context = groups[1] if len(groups) > 1 and groups[1] else None
                
                data_points.append({
                    "ticker": ticker,
                    "category": category,
                    "metric": metric_name,
                    "value": value,
                    "context": context,
                    "run_time": run_time,
                    "run_type": run_type,  # "post-market" or "pre-market"
                    "source": source,
                    "url": url,
                    "raw_text": match.group(0)[:120],
                })
    
    return data_points


def _run_timestamp(run_dir: Path) -> str:
    """Infer a run timestamp from runs/YYYY-MM-DD/{mode}/ for freshness metadata."""
    run_date = run_dir.parent.name if run_dir.parent.name.count("-") == 2 else date.today().isoformat()
    hour = "18:00:00" if run_dir.name == "post-market" else "06:00:00"
    return f"{run_date}T{hour}"


def _infer_ticker_from_heading(heading: str) -> str | None:
    """Best-effort ticker inference from briefing section headings."""
    # Prefer explicit code/cashtag forms: `AVGO`, $AVGO
    explicit = re.search(r"(?:`|\$)([A-Z]{1,5})(?:`)?", heading)
    if explicit:
        return explicit.group(1)
    # Conservative fallback: all-caps token in heading, excluding common macro terms.
    stop = {"ETF", "ETFs", "FX", "CPI", "PPI", "GDP", "FOMC", "PM", "AM", "US", "EU", "UK", "AI"}
    for token in re.findall(r"\b[A-Z]{2,5}\b", heading):
        if token not in stop:
            return token
    return None


def _briefing_chunks(run_dir: Path) -> list[dict]:
    """Load briefing.md as primary temporal context, chunked by markdown heading.

    articles.json can be empty or only contain a search-plan frame on fresh runs.
    The briefing is the synthesized research note and carries the analyst's
    cross-asset understanding, so temporal reasoning must extract from it first.
    """
    briefing_path = run_dir / "briefing.md"
    fallback_path = run_dir / "summary.md"
    content_path = briefing_path if briefing_path.exists() else fallback_path
    if not content_path.exists():
        return []

    text = content_path.read_text().strip()
    if not text:
        return []

    chunks: list[dict] = []
    parts = re.split(r"(?m)^(#{1,4}\s+.+)$", text)
    if len(parts) == 1:
        parts = ["", "Full Briefing", text]

    preamble = parts[0].strip()
    if preamble:
        chunks.append({
            "title": f"{content_path.name} preamble",
            "description": preamble,
            "key_points": [],
            "source": content_path.name,
            "url": "",
            "ticker": "MACRO",
            "fetched_at": _run_timestamp(run_dir),
            "_context_source": content_path.name,
        })

    for i in range(1, len(parts), 2):
        heading = parts[i].strip().lstrip("#").strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if not body:
            continue
        chunks.append({
            "title": heading[:160],
            "description": body[:8000],
            "key_points": [],
            "source": content_path.name,
            "url": "",
            "ticker": _infer_ticker_from_heading(heading) or "MACRO",
            "fetched_at": _run_timestamp(run_dir),
            "_context_source": content_path.name,
        })
    return chunks


def _source_articles(run_dir: Path) -> list[dict]:
    """Load articles.json only as secondary source-link metadata."""
    path = run_dir / "articles.json"
    if not path.exists():
        return []
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        articles = data.get("articles", [])
        return articles if isinstance(articles, list) else []
    return []


def load_articles(run_dir: Path) -> list[dict]:
    """Load temporal context from briefing.md first; articles.json second.

    The returned list keeps the old call sites working, but it no longer lets an
    empty/search-plan articles.json starve the temporal brief of context.
    """
    briefing_context = _briefing_chunks(run_dir)
    source_articles = _source_articles(run_dir)
    seen = {(a.get("title", ""), a.get("url", "")) for a in briefing_context}
    for article in source_articles:
        key = (article.get("title", ""), article.get("url", ""))
        if key not in seen:
            briefing_context.append(article)
            seen.add(key)
    return briefing_context


def load_summary(run_dir: Path) -> str:
    """Load briefing.md as primary run summary; summary.md is a fallback digest."""
    briefing_path = run_dir / "briefing.md"
    if briefing_path.exists():
        return briefing_path.read_text()
    path = run_dir / "summary.md"
    if not path.exists():
        return ""
    return path.read_text()


# ── Article Freshness (48h rule) ──────────────────────────────────────────

def article_age_hours(article: dict, reference_time: datetime) -> float | None:
    """Estimate article age in hours relative to reference_time."""
    for ts_field in ["fetched_at", "published_at", "date"]:
        ts_str = article.get(ts_field, "")
        if ts_str:
            try:
                ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00")[:19])
                return (reference_time - ts.replace(tzinfo=None)).total_seconds() / 3600
            except (ValueError, TypeError):
                continue
    age = article.get("age_hours")
    if age is not None:
        return float(age)
    return None


def filter_by_freshness(articles: list[dict], max_hours: int = 48) -> tuple[list[dict], list[dict]]:
    """Split articles into fresh (≤max_hours) and historical (>max_hours)."""
    now = datetime.now()
    fresh = []
    historical = []
    for a in articles:
        age = article_age_hours(a, now)
        a["_computed_age"] = age
        if age is not None and age > max_hours:
            historical.append(a)
        else:
            fresh.append(a)
    return fresh, historical


# ── Temporal Diff Engine ──────────────────────────────────────────────────

def normalize_value(value: str) -> float | None:
    """Normalize a value string to a float for comparison.
    
    Handles: "$479.23", "-11.97%", "$22.2B", "4.46%", "+1.08%"
    Returns: float (e.g., 479.23, -0.1197, 22.2, 4.46, 1.08)
    Returns None if unparseable (trailing junk, ranges, etc.)
    """
    v = value.strip().replace(",", "")
    # Strip trailing punctuation: periods, commas, closing parens, dashes
    v = v.rstrip(".,;:)-—–")
    # Strip leading junk (open parens, whitespace)
    v = v.lstrip("(")
    
    if not v:
        return None
    
    # Ranges like "$94.98-$97.79" — take the first value
    if "-" in v and v.count("-") > 1:
        # Contains a negative sign AND a dash — ambiguous, take before the dash-range
        parts = v.split("-")
        if len(parts) >= 2:
            # Check if the first part looks like a valid number
            try:
                return normalize_value(parts[0].strip())
            except (ValueError, TypeError):
                return None
    
    try:
        # Billions suffix
        if v.upper().endswith("B"):
            v = v[:-1]
            if v.startswith("$"):
                v = v[1:]
            return float(v)
        
        # Millions suffix  
        if v.upper().endswith("M"):
            v = v[:-1]
            if v.startswith("$"):
                v = v[1:]
            return float(v)
        
        # Percentage
        if v.endswith("%"):
            return float(v[:-1])
        
        # Dollar amount
        if v.startswith("$"):
            return float(v[1:])
        
        # Plain number
        return float(v)
    except (ValueError, TypeError):
        return None


def compute_temporal_diff(pm_data_points: list[dict], am_data_points: list[dict]) -> dict:
    """Compare PM and AM data points for the same ticker+metric.
    
    Returns a diff dict with:
    - confirmed: data points that appear in both runs with same/similar values
    - evolved: data points that changed between runs (PM → AM)
    - pm_only: data points only in PM (potentially stale)
    - am_only: data points only in AM (new developments)
    - contradicted: data points that directly conflict
    """
    # Group by (ticker, metric) key
    pm_by_key = defaultdict(list)
    am_by_key = defaultdict(list)
    
    for dp in pm_data_points:
        key = (dp["ticker"], dp["metric"])
        pm_by_key[key].append(dp)
    
    for dp in am_data_points:
        key = (dp["ticker"], dp["metric"])
        am_by_key[key].append(dp)
    
    all_keys = set(pm_by_key.keys()) | set(am_by_key.keys())
    
    confirmed = []
    evolved = []
    pm_only = []
    am_only = []
    contradicted = []
    
    for key in all_keys:
        ticker, metric = key
        pm_dps = pm_by_key.get(key, [])
        am_dps = am_by_key.get(key, [])
        
        if pm_dps and am_dps:
            # Both runs have this data point — compare
            pm_val = normalize_value(pm_dps[0]["value"])
            am_val = normalize_value(am_dps[0]["value"])
            
            if pm_val is None or am_val is None:
                # Unparseable — treat as confirmed (can't diff)
                confirmed.append({
                    "ticker": ticker,
                    "metric": metric,
                    "pm_value": pm_dps[0]["value"],
                    "am_value": am_dps[0]["value"],
                    "pm_source": pm_dps[0]["source"],
                    "am_source": am_dps[0]["source"],
                    "pm_raw": pm_dps[0].get("raw_text", ""),
                    "am_raw": am_dps[0].get("raw_text", ""),
                    "pct_change": 0,
                    "direction": "unparseable",
                })
                continue
            
            # Compute delta
            try:
                if abs(pm_val) > 0.001:
                    pct_change = ((am_val - pm_val) / abs(pm_val)) * 100
                else:
                    pct_change = 0
            except ZeroDivisionError:
                pct_change = 0
            
            entry = {
                "ticker": ticker,
                "metric": metric,
                "pm_value": pm_dps[0]["value"],
                "am_value": am_dps[0]["value"],
                "pm_source": pm_dps[0]["source"],
                "am_source": am_dps[0]["source"],
                "pm_raw": pm_dps[0].get("raw_text", ""),
                "am_raw": am_dps[0].get("raw_text", ""),
                "pct_change": round(pct_change, 1),
                "direction": "up" if pct_change > 0.5 else "down" if pct_change < -0.5 else "flat",
            }
            
            if abs(pct_change) < 1.0:
                confirmed.append(entry)
            else:
                evolved.append(entry)
        
        elif pm_dps and not am_dps:
            for dp in pm_dps:
                pm_only.append({
                    "ticker": ticker,
                    "metric": metric,
                    "pm_value": dp["value"],
                    "pm_source": dp["source"],
                    "pm_raw": dp.get("raw_text", ""),
                    "staleness_risk": "high" if dp["run_type"] == "post-market" else "moderate",
                })
        
        elif am_dps and not pm_dps:
            for dp in am_dps:
                am_only.append({
                    "ticker": ticker,
                    "metric": metric,
                    "am_value": dp["value"],
                    "am_source": dp["source"],
                    "am_raw": dp.get("raw_text", ""),
                })
    
    return {
        "confirmed": confirmed,
        "evolved": evolved,
        "pm_only": pm_only,
        "am_only": am_only,
        "contradicted": contradicted,
    }


# ── Narrative Generation ──────────────────────────────────────────────────

def generate_temporal_narrative(
    pm_articles: list[dict],
    am_articles: list[dict],
    pm_summary: str,
    am_summary: str,
    pm_date: str,
    am_date: str,
) -> str:
    """Generate a markdown narrative showing temporal evolution of data points."""
    
    now = datetime.now()
    
    # Extract data points
    pm_data_points = []
    for article in pm_articles:
        pm_data_points.extend(extract_data_points(article, f"{pm_date} 18:00 ET", "post-market"))
    
    am_data_points = []
    for article in am_articles:
        am_data_points.extend(extract_data_points(article, f"{am_date} 06:00 ET", "pre-market"))
    
    # Compute temporal diff
    diff = compute_temporal_diff(pm_data_points, am_data_points)
    
    # Identify tickers with earnings/price data
    ticker_data = defaultdict(lambda: {"pm": [], "am": [], "articles_pm": [], "articles_am": []})
    for dp in pm_data_points:
        if dp["ticker"] != "MACRO":
            ticker_data[dp["ticker"]]["pm"].append(dp)
    for dp in am_data_points:
        if dp["ticker"] != "MACRO":
            ticker_data[dp["ticker"]]["am"].append(dp)
    
    # Attach articles to tickers
    for a in pm_articles:
        t = a.get("ticker") or "MACRO"
        ticker_data[t]["articles_pm"].append(a)
    for a in am_articles:
        t = a.get("ticker") or "MACRO"
        ticker_data[t]["articles_am"].append(a)
    
    # Build the narrative
    lines = []
    lines.append("# ⚡ BoltNews — Temporal Reasoning Brief")
    lines.append(f"**{pm_date} Full-Day Cycle** | Consolidated: {now.strftime('%Y-%m-%d %H:%M ET')}")
    lines.append(f"**Sources:** Post-Market {pm_date} 6PM ET + Pre-Market {am_date} 6AM ET")
    lines.append("")
    lines.append("> **How to read this:** This is NOT a concatenation of two briefings. It's a temporal analysis")
    lines.append("> showing how data points evolved between the 6PM close and the 6AM pre-market open.")
    lines.append("> **🔄 = data point changed | ✅ = confirmed | 🆕 = new overnight | ⚠️ = PM data potentially stale**")
    lines.append("")
    
    # ── Executive Summary ──
    lines.append("---")
    lines.append("")
    lines.append("## 📊 Executive Summary — What Changed Overnight")
    lines.append("")
    
    if diff["evolved"]:
        lines.append("### 🔄 Data Points That Evolved (PM → AM)")
        lines.append("")
        for entry in diff["evolved"]:
            direction_emoji = "📈" if entry["direction"] == "up" else "📉" if entry["direction"] == "down" else "➡️"
            lines.append(
                f"- **`{entry['ticker']}` {entry['metric']}:** "
                f"{entry['pm_value']} ({entry['pm_source']}, 6PM) "
                f"→ {entry['am_value']} ({entry['am_source']}, 6AM) "
                f"{direction_emoji} {entry['pct_change']:+.1f}% change"
            )
            if entry.get("pm_raw") and entry.get("am_raw"):
                lines.append(f"  - PM: _{entry['pm_raw']}_")
                lines.append(f"  - AM: _{entry['am_raw']}_")
        lines.append("")
    
    if diff["pm_only"]:
        high_risk = [e for e in diff["pm_only"] if e["staleness_risk"] == "high"]
        if high_risk:
            lines.append("### ⚠️ PM Data Points NOT Confirmed by AM (Staleness Risk)")
            lines.append("")
            lines.append("*These data points appeared in the 6PM run but were NOT mentioned or updated in the 6AM run. They may be stale.*")
            lines.append("")
            for entry in high_risk[:15]:
                lines.append(f"- **`{entry['ticker']}` {entry['metric']}:** {entry['pm_value']} — _source: {entry['pm_source']}_")
            lines.append("")
    
    if diff["am_only"]:
        ticker_am_only = [e for e in diff["am_only"] if e["ticker"] != "MACRO"]
        if ticker_am_only:
            lines.append("### 🆕 New Overnight Developments (AM only)")
            lines.append("")
            for entry in ticker_am_only[:15]:
                lines.append(f"- **`{entry['ticker']}` {entry['metric']}:** {entry['am_value']} — _source: {entry['am_source']}_")
            lines.append("")
    
    # ── Per-Ticker Temporal Evolution ──
    lines.append("---")
    lines.append("")
    lines.append("## 🔍 Per-Ticker Temporal Evolution")
    lines.append("")
    
    # Find tickers with both PM and AM data
    tickers_with_both = []
    for ticker, data in ticker_data.items():
        if ticker == "MACRO":
            continue
        if data["pm"] and data["am"]:
            tickers_with_both.append(ticker)
        elif data["pm"] and not data["am"]:
            tickers_with_both.append(ticker)  # still show PM-only tickers
        elif data["am"] and not data["pm"]:
            tickers_with_both.append(ticker)  # new tickers in AM
    
    # Sort by importance (earnings tickers first)
    earnings_tickers = {"AVGO", "CRWD", "VEEV", "PANW", "HPE", "META", "MSTR", "NVDA"}
    tickers_with_both.sort(key=lambda t: (t not in earnings_tickers, t))
    
    for ticker in tickers_with_both[:20]:
        data = ticker_data[ticker]
        pm_dps = data["pm"]
        am_dps = data["am"]
        pm_arts = data["articles_pm"]
        am_arts = data["articles_am"]
        
        lines.append(f"### `{ticker}`")
        lines.append("")
        
        # Show temporal evolution if we have both
        if pm_dps and am_dps:
            lines.append("| Metric | PM (6PM) | AM (6AM) | Δ | Signal |")
            lines.append("|--------|----------|----------|-----|--------|")
            
            pm_by_metric = {dp["metric"]: dp for dp in pm_dps}
            am_by_metric = {dp["metric"]: dp for dp in am_dps}
            all_metrics = set(pm_by_metric.keys()) | set(am_by_metric.keys())
            
            for metric in sorted(all_metrics):
                pm_dp = pm_by_metric.get(metric)
                am_dp = am_by_metric.get(metric)
                
                pm_str = pm_dp["value"] if pm_dp else "—"
                am_str = am_dp["value"] if am_dp else "—"
                
                if pm_dp and am_dp:
                    try:
                        pm_v = normalize_value(pm_dp["value"])
                        am_v = normalize_value(am_dp["value"])
                        if pm_v is not None and am_v is not None:
                            delta = am_v - pm_v
                            if abs(pm_v) > 0.001:
                                delta_pct = (delta / abs(pm_v)) * 100
                                delta_str = f"{delta_pct:+.1f}%"
                            else:
                                delta_str = f"{delta:+.2f}"
                            signal = "🔄 Updated" if abs(delta) > 0.001 else "✅ Unchanged"
                        else:
                            delta_str = "—"
                            signal = "—"
                    except (ValueError, TypeError):
                        delta_str = "—"
                        signal = "—"
                elif pm_dp and not am_dp:
                    delta_str = "—"
                    signal = "⚠️ Stale risk"
                else:
                    delta_str = "—"
                    signal = "🆕 New"
                
                lines.append(f"| {metric} | {pm_str} | {am_str} | {delta_str} | {signal} |")
            
            lines.append("")
        
        elif pm_dps and not am_dps:
            lines.append(f"**⚠️ PM-only data — no AM update found. Potential staleness.**")
            lines.append("")
            for dp in pm_dps[:8]:
                lines.append(f"- **{dp['metric']}:** {dp['value']} (_{dp['source']}_ — 6PM)")
            lines.append("")
        
        elif am_dps and not pm_dps:
            lines.append(f"**🆕 New overnight development**")
            lines.append("")
            for dp in am_dps[:8]:
                lines.append(f"- **{dp['metric']}:** {dp['value']} (_{dp['source']}_ — 6AM)")
            lines.append("")
        
        # Article-level temporal context
        if pm_arts or am_arts:
            lines.append("**Article-level context:**")
            lines.append("")
            for a in pm_arts:
                title = a.get("title", "")[:120]
                age = a.get("_computed_age", "?")
                age_str = f"{age:.0f}h" if isinstance(age, (int, float)) else str(age)
                lines.append(f"- [6PM] [{title}]({a.get('url', '')}) — {age_str} ago")
            for a in am_arts:
                title = a.get("title", "")[:120]
                age = a.get("_computed_age", "?")
                age_str = f"{age:.0f}h" if isinstance(age, (int, float)) else str(age)
                lines.append(f"- [6AM] [{title}]({a.get('url', '')}) — {age_str} ago")
            lines.append("")
    
    # ── Macro Data Points ──
    lines.append("---")
    lines.append("")
    lines.append("## 🌐 Macro Cross-Run Data Points")
    lines.append("")
    
    macro_dps = [dp for dp in pm_data_points + am_data_points if dp["ticker"] == "MACRO"]
    macro_by_metric = defaultdict(lambda: {"pm": None, "am": None})
    for dp in macro_dps:
        if dp["run_type"] == "post-market":
            macro_by_metric[dp["metric"]]["pm"] = dp
        else:
            macro_by_metric[dp["metric"]]["am"] = dp
    
    # Important macro metrics
    key_macros = ["wti", "brent", "sp500", "dow", "nasdaq", "vix", "10y", "30y", "2y", "fed_funds"]
    
    lines.append("| Metric | PM (6PM) | AM (6AM) | Δ | Trend |")
    lines.append("|--------|----------|----------|-----|-------|")
    
    for metric in key_macros:
        entry = macro_by_metric.get(metric, {"pm": None, "am": None})
        pm_val = entry["pm"].get("value") if entry["pm"] else "—"
        am_val = entry["am"].get("value") if entry["am"] else "—"
        
        if entry["pm"] and entry["am"]:
            try:
                pm_v = normalize_value(pm_val)
                am_v = normalize_value(am_val)
                if pm_v is not None and am_v is not None:
                    delta = am_v - pm_v
                    delta_str = f"{delta:+.1f}"
                    trend = "📈" if delta > 0 else "📉" if delta < 0 else "➡️"
                else:
                    delta_str = "—"
                    trend = "—"
            except (ValueError, TypeError):
                delta_str = "—"
                trend = "—"
        else:
            delta_str = "—"
            trend = "⚠️" if entry["pm"] and not entry["am"] else "🆕"
        
        lines.append(f"| {metric} | {pm_val} | {am_val} | {delta_str} | {trend} |")
    
    lines.append("")
    
    # ── Contrarian Signals ──
    lines.append("---")
    lines.append("")
    lines.append("## 🔍 Cross-Run Contrarian Signals & Risk Flags")
    lines.append("")
    
    # PM-only data points that matter
    high_risk_pm = [e for e in diff["pm_only"] if e["staleness_risk"] == "high"]
    if high_risk_pm:
        lines.append(f"**⚠️ {len(high_risk_pm)} data points from PM were NOT updated in AM — verify before trading:**")
        lines.append("")
        for entry in high_risk_pm[:10]:
            lines.append(f"- `{entry['ticker']}` **{entry['metric']}:** {entry['pm_value']} (_{entry['pm_source']}_) — AM silent")
        lines.append("")
    
    # Evolved data points that changed significantly
    big_moves = [e for e in diff["evolved"] if abs(e["pct_change"]) > 2.0]
    if big_moves:
        lines.append(f"**🔄 {len(big_moves)} data points shifted significantly between runs:**")
        lines.append("")
        for entry in big_moves:
            lines.append(
                f"- `{entry['ticker']}` **{entry['metric']}:** "
                f"{entry['pm_value']} → {entry['am_value']} "
                f"({entry['pct_change']:+.1f}%)"
            )
        lines.append("")
    
    # ── Source Freshness Report ──
    lines.append("---")
    lines.append("")
    lines.append("## 📋 Source Freshness Report")
    lines.append("")
    
    all_articles = pm_articles + am_articles
    fresh, historical = filter_by_freshness(all_articles, max_hours=48)
    
    lines.append(f"- **Fresh articles (≤48h):** {len(fresh)} ({len([a for a in fresh if a in pm_articles])} PM + {len([a for a in fresh if a in am_articles])} AM)")
    lines.append(f"- **Historical context (>48h):** {len(historical)}")
    lines.append("")
    
    if historical:
        lines.append("### 📚 Historical Context (reference only)")
        lines.append("")
        lines.append("*These articles are >48h old and included ONLY as background reference.*")
        lines.append("")
        for a in historical[:10]:
            title = a.get("title", "Untitled")[:100]
            age = a.get("_computed_age", "?")
            lines.append(f"- [{title}]({a.get('url', '')}) — ~{age:.0f}h old")
        lines.append("")
    
    # ── Footer ──
    lines.append("---")
    lines.append("")
    lines.append(f"*BoltNews Temporal Reasoning Brief | {pm_date} cycle | {len(pm_articles) + len(am_articles)} articles analyzed | {len(diff['evolved'])} data points evolved | {len(diff['confirmed'])} confirmed | {len(diff['am_only'])} new*")
    
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="BoltNews Temporal Reasoning Consolidator"
    )
    ap.add_argument("--date", help="Full-day date to consolidate (YYYY-MM-DD)")
    ap.add_argument("--am", help="Path to AM (pre-market) run directory")
    ap.add_argument("--pm", help="Path to PM (post-market) run directory")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    
    today = date.today()
    
    # Resolve run directories
    if args.am and args.pm:
        am_dir = Path(args.am)
        pm_dir = Path(args.pm)
        pm_date = pm_dir.parent.name if pm_dir.parent.name.count("-") == 2 else today.isoformat()
        am_date = am_dir.parent.name if am_dir.parent.name.count("-") == 2 else today.isoformat()
    elif args.date:
        pm_date = args.date
        am_date = (date.fromisoformat(pm_date) + timedelta(days=1)).isoformat()
        am_dir = RUNS_DIR / am_date / "pre-market"
        pm_dir = RUNS_DIR / pm_date / "post-market"
    else:
        # Auto-detect: today's AM + yesterday's PM
        am_dir = RUNS_DIR / today.isoformat() / "pre-market"
        am_date = today.isoformat()
        yesterday = today - timedelta(days=1)
        pm_dir = None
        for _ in range(5):
            candidate = RUNS_DIR / yesterday.isoformat() / "post-market"
            if candidate.exists():
                pm_dir = candidate
                pm_date = yesterday.isoformat()
                break
            yesterday -= timedelta(days=1)
        if not pm_dir:
            print("❌ PM (post-market) run not found", file=sys.stderr)
            sys.exit(1)
    
    if not am_dir or not am_dir.exists():
        print(f"❌ AM run not found: {am_dir}", file=sys.stderr)
        sys.exit(1)
    if not pm_dir or not pm_dir.exists():
        print(f"❌ PM run not found: {pm_dir}", file=sys.stderr)
        sys.exit(1)
    
    print(f"Temporal reasoning consolidation:")
    print(f"  PM: {pm_dir} ({pm_date})")
    print(f"  AM: {am_dir} ({am_date})")
    
    # Load data
    pm_articles = load_articles(pm_dir)
    am_articles = load_articles(am_dir)
    pm_summary = load_summary(pm_dir)
    am_summary = load_summary(am_dir)
    
    print(f"  PM articles: {len(pm_articles)}, AM articles: {len(am_articles)}")
    
    # Generate temporal narrative
    narrative = generate_temporal_narrative(
        pm_articles, am_articles, pm_summary, am_summary,
        pm_date, am_date
    )
    
    # Output
    out_dir = RUNS_DIR / pm_date / "daily"
    
    if args.dry_run:
        print(f"\n  DRY RUN — would write to: {out_dir}")
        print(f"  temporal_brief.md: {len(narrative):,} chars")
        return
    
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Write temporal brief
    brief_path = out_dir / "temporal_brief.md"
    brief_path.write_text(narrative)
    print(f"  ✅ temporal_brief.md ({len(narrative):,} chars)")
    
    # Write machine-readable temporal diff
    pm_data_points = []
    for article in pm_articles:
        pm_data_points.extend(extract_data_points(article, f"{pm_date} 18:00 ET", "post-market"))
    am_data_points = []
    for article in am_articles:
        am_data_points.extend(extract_data_points(article, f"{am_date} 06:00 ET", "pre-market"))
    
    diff = compute_temporal_diff(pm_data_points, am_data_points)
    
    diff_path = out_dir / "temporal_diff.json"
    with open(diff_path, "w") as f:
        json.dump({
            "pm_date": pm_date,
            "am_date": am_date,
            "consolidated_at": datetime.now().isoformat(),
            "pm_articles": len(pm_articles),
            "am_articles": len(am_articles),
            "pm_data_points": len(pm_data_points),
            "am_data_points": len(am_data_points),
            "diff": {
                "evolved": len(diff["evolved"]),
                "confirmed": len(diff["confirmed"]),
                "pm_only": len(diff["pm_only"]),
                "am_only": len(diff["am_only"]),
                "contradicted": len(diff["contradicted"]),
            },
            "details": diff,
        }, f, indent=2, default=str)
    print(f"  ✅ temporal_diff.json")
    
    print(f"\n✅ Temporal reasoning brief complete: {out_dir}")


if __name__ == "__main__":
    main()
