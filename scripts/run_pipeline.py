#!/usr/bin/env python3.12
"""
BoltNews — Master Pipeline Orchestrator.
Run modes: pre-market (6AM ET) or post-market (6PM ET).
Stages: universe → source discovery → article fetch → dedup → summarize → dashboard → deploy.
"""
import argparse
import json
import sys
from datetime import datetime, date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
DATA_DIR = PROJECT_ROOT / "data"
RUNS_DIR = PROJECT_ROOT / "runs"

# === CLI ===
parser = argparse.ArgumentParser(description="BoltNews Pipeline")
parser.add_argument("--mode", choices=["pre-market", "post-market"], default="pre-market",
                    help="Pre-market (AM) or post-market (PM) run")
parser.add_argument("--date", type=str, default=None,
                    help="Override date (YYYY-MM-DD). Default: today.")
parser.add_argument("--skip-universe", action="store_true", help="Skip universe rebuild")
parser.add_argument("--skip-sources", action="store_true", help="Skip source discovery")
parser.add_argument("--skip-scrape", action="store_true", help="Skip article scraping (use cached)")
parser.add_argument("--dry-run", action="store_true", help="Print plan, don't execute")
args = parser.parse_args()

run_date = args.date or date.today().isoformat()
run_dir = RUNS_DIR / run_date / args.mode
run_dir.mkdir(parents=True, exist_ok=True)

print(f"=== BoltNews Pipeline ===")
print(f"Date: {run_date} | Mode: {args.mode}")
print(f"Output: {run_dir}")
print()

# === Stage 1: Universe ===
universe_path = DATA_DIR / "universe.json"
if not args.skip_universe:
    import subprocess
    print("[1/6] Building ticker universe...")
    result = subprocess.run(
        ["python3.12", str(SCRIPTS_DIR / "build_universe.py")],
        capture_output=True, text=True, timeout=120
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"ERROR building universe: {result.stderr}", file=sys.stderr)
        sys.exit(1)
else:
    print("[1/6] Skipping universe rebuild (--skip-universe)")

# Load universe
with open(universe_path) as f:
    universe = json.load(f)
tickers = [t["ticker"] for t in universe["tickers"]]
print(f"  → {len(tickers)} tickers in watchlist")

# === Stage 2: Source Discovery (weekly only) ===
sources_path = DATA_DIR / "sources.json"
if not args.skip_sources and date.today().weekday() == 0:  # Monday only
    print("[2/6] Running source discovery (weekly)...")
    # TODO: implement source discovery
    print("  → Source discovery: stub (seeded sources loaded)")
else:
    print("[2/6] Source discovery: skipped (daily run, using existing sources)")

# === Stage 3: Article Fetch ===
articles_path = run_dir / "articles.json"
if not args.skip_scrape:
    print(f"[3/6] Fetching articles for {len(tickers)} tickers + market topics...")
    # This is the big one — delegate to fetch_articles.py
    import subprocess
    result = subprocess.run(
        [
            "python3.12", str(SCRIPTS_DIR / "fetch_articles.py"),
            "--mode", args.mode,
            "--universe", str(universe_path),
            "--sources", str(sources_path),
            "--output", str(articles_path),
            "--date", run_date,
        ],
        capture_output=True, text=True, timeout=600  # 10 min for article fetch
    )
    print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
    if result.returncode != 0:
        print(f"ERROR fetching articles: {result.stderr[-1000:]}", file=sys.stderr)
        # Non-fatal — continue with what we have
else:
    print("[3/6] Skipping article fetch (--skip-scrape)")

# === Stage 4: Deduplicate + Summarize ===
summary_path = run_dir / "summary.md"
print("[4/6] Deduplicating + summarizing articles...")
import subprocess
result = subprocess.run(
    [
        "python3.12", str(SCRIPTS_DIR / "summarize.py"),
        "--input", str(articles_path),
        "--output", str(summary_path),
        "--mode", args.mode,
        "--date", run_date,
    ],
    capture_output=True, text=True, timeout=300
)
print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
if result.returncode != 0:
    print(f"ERROR summarizing: {result.stderr[-1000:]}", file=sys.stderr)

# === Stage 5: Build Dashboard ===
dashboard_path = run_dir / "dashboard.html"
print("[5/6] Building HTML dashboard...")
result = subprocess.run(
    [
        "python3.12", str(SCRIPTS_DIR / "build_dashboard.py"),
        "--input", str(articles_path),
        "--summary", str(summary_path),
        "--output", str(dashboard_path),
        "--mode", args.mode,
        "--date", run_date,
    ],
    capture_output=True, text=True, timeout=120
)
print(result.stdout[-1000:] if len(result.stdout) > 1000 else result.stdout)
if result.returncode != 0:
    print(f"ERROR building dashboard: {result.stderr[-1000:]}", file=sys.stderr)

# === Stage 6: Deploy ===
print("[6/6] Deploying to GitHub + GitHub Pages...")
result = subprocess.run(
    [
        "python3.12", str(SCRIPTS_DIR / "deploy.py"),
        "--run-dir", str(run_dir),
        "--mode", args.mode,
        "--date", run_date,
    ],
    capture_output=True, text=True, timeout=180
)
print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
if result.returncode != 0:
    print(f"ERROR deploying: {result.stderr[-1000:]}", file=sys.stderr)

# === Summary ===
print()
print("=== Pipeline Complete ===")
print(f"Summary: {summary_path}")
print(f"Dashboard: {dashboard_path}")
print(f"Articles: {articles_path}")
