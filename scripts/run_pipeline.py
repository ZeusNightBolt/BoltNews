#!/usr/bin/env python3.12
"""
BoltNews — Master Pipeline Orchestrator.
Run modes: pre-market (6AM ET), post-market (6PM ET), weekend (auto-detected).
Stages: universe (Mon only) → plan generation → [agent executes searches] → 
        dedup + summarize → dashboard → deploy to GH Pages.
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
DATA_DIR = PROJECT_ROOT / "data"
RUNS_DIR = PROJECT_ROOT / "runs"


def is_weekend(d: date | None = None) -> bool:
    return (d or date.today()).weekday() >= 5


def safe_run(cmd: list[str], timeout: int = 120, label: str = "") -> subprocess.CompletedProcess:
    """Run a subprocess, print output, return result."""
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.stdout:
        # Print last 2000 chars of stdout
        out = result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout
        print(out)
    if result.returncode != 0 and label:
        print(f"[{label}] FAILED (exit {result.returncode}): {result.stderr[-500:]}", file=sys.stderr)
    return result


# === CLI ===
parser = argparse.ArgumentParser(description="BoltNews Pipeline")
parser.add_argument("--mode", choices=["pre-market", "post-market", "weekend"], default=None,
                    help="Auto-detected if not set.")
parser.add_argument("--date", type=str, default=None,
                    help="Override date (YYYY-MM-DD). Default: today.")
parser.add_argument("--skip-universe", action="store_true", help="Skip universe rebuild")
parser.add_argument("--skip-deploy", action="store_true", help="Skip GitHub deploy")
parser.add_argument("--dry-run", action="store_true", help="Print plan, don't execute")
args = parser.parse_args()

run_date = args.date or date.today().isoformat()
today = date.fromisoformat(run_date)

# Auto-detect mode
if args.mode is None:
    if is_weekend(today):
        args.mode = "weekend"
    else:
        args.mode = "pre-market"
elif is_weekend(today):
    args.mode = "weekend"

run_dir = RUNS_DIR / run_date / args.mode

if args.dry_run:
    print(f"=== BoltNews Pipeline (DRY RUN) ===")
    print(f"Date: {run_date} ({today.strftime('%A')}) | Mode: {args.mode}")
    print(f"Output dir: {run_dir}")
    print(f"Universe: {'rebuild (Monday)' if today.weekday() == 0 else 'skip (not Monday)'}")
    print(f"Deploy: {'skip' if args.skip_deploy else 'GitHub + GH Pages'}")
    print(f"Files that would be created:")
    print(f"  {run_dir}/articles.json")
    print(f"  {run_dir}/summary.md")
    print(f"  {run_dir}/dashboard.html")
    sys.exit(0)

run_dir.mkdir(parents=True, exist_ok=True)

print(f"=== BoltNews Pipeline ===")
print(f"Date: {run_date} ({today.strftime('%A')}) | Mode: {args.mode}" +
      (" (weekend — narrative/analysis)" if is_weekend(today) else ""))
print(f"Output: {run_dir}")
print()

# ═══════════════════════
# Stage 1: Universe (MONDAYS ONLY)
# ═══════════════════════
universe_path = DATA_DIR / "universe.json"

if not args.skip_universe and today.weekday() == 0:  # Monday
    print("[1/6] Building ticker universe (Monday refresh)...")
    result = safe_run(
        ["python3.12", str(SCRIPTS_DIR / "build_universe.py")],
        timeout=120, label="universe"
    )
    if result.returncode != 0:
        print("FATAL: Universe build failed.", file=sys.stderr)
        sys.exit(1)
else:
    reason = "skip" if args.skip_universe else f"not Monday (weekday={today.weekday()})"
    print(f"[1/6] Universe rebuild: skipped ({reason})")

# Load universe (must exist)
if not universe_path.exists():
    print("FATAL: universe.json not found. Run build_universe.py first.", file=sys.stderr)
    sys.exit(1)

with open(universe_path) as f:
    universe = json.load(f)
tickers = [t["ticker"] for t in universe["tickers"]]
print(f"  → {len(tickers)} tickers in watchlist")

# ═══════════════════════
# Stage 2: Source Discovery (stub)
# ═══════════════════════
print("[2/6] Source discovery: using existing sources.json")

# ═══════════════════════
# Stage 3: Article Fetch (PLAN ONLY — agent executes searches)
# ═══════════════════════
articles_path = run_dir / "articles.json"
sources_path = DATA_DIR / "sources.json"

print(f"[3/6] Generating search plan...")
result = safe_run(
    [
        "python3.12", str(SCRIPTS_DIR / "fetch_articles.py"),
        "--mode", args.mode,
        "--universe", str(universe_path),
        "--sources", str(sources_path),
        "--output", str(articles_path),
        "--date", run_date,
        "--plan-only",
    ],
    timeout=30, label="fetch_articles"
)
if result.returncode != 0:
    print("WARNING: Search plan generation failed. Agent will use defaults.", file=sys.stderr)

# ═══════════════════════
# Stage 4: Summarize (agent writes articles.json, then summarize.py runs)
# ═══════════════════════
summary_path = run_dir / "summary.md"
print("[4/6] Summarizing articles...")
result = safe_run(
    [
        "python3.12", str(SCRIPTS_DIR / "summarize.py"),
        "--input", str(articles_path),
        "--output", str(summary_path),
        "--mode", args.mode,
        "--date", run_date,
    ],
    timeout=300, label="summarize"
)
if result.returncode != 0:
    print("WARNING: Summarizer failed. Dashboard will render from raw articles.", file=sys.stderr)

# ═══════════════════════
# Stage 5: Build Dashboard
# ═══════════════════════
dashboard_path = run_dir / "dashboard.html"
print("[5/6] Building dashboard...")
result = safe_run(
    [
        "python3.12", str(SCRIPTS_DIR / "build_dashboard.py"),
        "--input", str(articles_path),
        "--summary", str(summary_path),
        "--output", str(dashboard_path),
        "--mode", args.mode,
        "--date", run_date,
    ],
    timeout=120, label="dashboard"
)
if result.returncode != 0:
    print("ERROR: Dashboard build failed.", file=sys.stderr)
    if not args.skip_deploy:
        print("Skipping deploy — dashboard is required.", file=sys.stderr)
        sys.exit(1)

# ═══════════════════════
# Stage 6: Deploy to GitHub Pages
# ═══════════════════════
if args.skip_deploy:
    print("[6/6] Deploy: SKIPPED (--skip-deploy)")
else:
    print("[6/6] Deploying to GitHub + GitHub Pages...")
    result = safe_run(
        [
            "python3.12", str(SCRIPTS_DIR / "deploy.py"),
            "--run-dir", str(run_dir),
            "--mode", args.mode,
            "--date", run_date,
        ],
        timeout=180, label="deploy"
    )
    if result.returncode != 0:
        print("ERROR: Deploy failed. Artifacts are on disk but NOT on GitHub Pages.", file=sys.stderr)
        sys.exit(1)

# ═══════════════════════
# Complete
# ═══════════════════════
print()
print("=== Pipeline Complete ===")
print(f"Summary:  {summary_path}")
print(f"Dashboard: {dashboard_path}")
print(f"Articles: {articles_path}")
print(f"GH Pages: {PAGES_URL if 'PAGES_URL' in dir() else 'https://zeusnightbolt.github.io/BoltNews/'}")
