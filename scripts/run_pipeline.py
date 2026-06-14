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
from datetime import datetime, date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
DATA_DIR = PROJECT_ROOT / "data"
RUNS_DIR = PROJECT_ROOT / "runs"


def is_weekend(d: date | None = None) -> bool:
    return (d or date.today()).weekday() >= 5


def safe_run(cmd: list[str], timeout: int = 120, label: str = "") -> subprocess.CompletedProcess:
    """Run a subprocess, print output, return result."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        print(
            f"[{label or 'subprocess'}] TIMEOUT after {timeout}s: {' '.join(cmd)}",
            file=sys.stderr,
        )
        if exc.stdout:
            print(str(exc.stdout)[-2000:])
        if exc.stderr:
            print(str(exc.stderr)[-1000:], file=sys.stderr)
        return subprocess.CompletedProcess(cmd, 124, exc.stdout or "", exc.stderr or "")
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
parser.add_argument("--resume", action="store_true",
                    help="Deprecated no-op: existing run artifacts are preserved by default.")
parser.add_argument("--fresh", action="store_true",
                    help="Explicitly clear generated run artifacts before starting. Dangerous for agent-assisted runs.")
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
# If --mode is explicitly supplied, honor it. Weekend coercion belongs only to
# auto-detection; otherwise cron/debug runs silently do the wrong mode.

run_dir = RUNS_DIR / run_date / args.mode

if args.dry_run:
    print(f"=== BoltNews Pipeline (DRY RUN) ===")
    print(f"Date: {run_date} ({today.strftime('%A')}) | Mode: {args.mode}")
    print(f"Output dir: {run_dir}")
    print(f"Universe: {'rebuild (Monday)' if today.weekday() == 0 else 'skip (not Monday)'}")
    print(f"Deploy: {'skip' if args.skip_deploy else 'GitHub + GH Pages'}")
    print("Deterministic script stages create/verify search_plan.json and then require")
    print("agent-populated articles.json + briefing.md before summary/dashboard/deploy.")
    print(f"Files required for successful finalization:")
    print(f"  {run_dir}/search_plan.json")
    print(f"  {run_dir}/articles.json  (fresh extracted article feed)")
    print(f"  {run_dir}/briefing.md    (canonical synthesized research note)")
    print(f"  {run_dir}/summary.md")
    print(f"  {run_dir}/dashboard.html")
    sys.exit(0)

run_dir.mkdir(parents=True, exist_ok=True)

# Fresh-run hygiene is opt-in. The documented pipeline has an LLM-assisted
# collection/synthesis boundary between search_plan.json and articles.json /
# briefing.md. Clearing by default deleted those agent-populated artifacts and
# made weekend cron runs fail or report misleading partial state.
def clear_generated_run_state(path: Path) -> None:
    generated_files = [
        "articles.json",
        "articles_enriched.json",
        "summary.md",
        "briefing.md",
        "dashboard.html",
        "search_plan.json",
        "feed_cache.json",
        "raw_feeds.json",
        "extraction_cache.json",
    ]
    removed = []
    for name in generated_files:
        target = path / name
        if target.exists():
            target.unlink()
            removed.append(name)
    for cache_dir_name in ["cache", ".cache", "feeds", "raw"]:
        cache_dir = path / cache_dir_name
        if cache_dir.exists() and cache_dir.is_dir():
            for child in cache_dir.rglob("*"):
                if child.is_file():
                    child.unlink()
            for child in sorted(cache_dir.rglob("*"), reverse=True):
                if child.is_dir():
                    child.rmdir()
            cache_dir.rmdir()
            removed.append(f"{cache_dir_name}/")
    print(f"Fresh run: cleared {len(removed)} generated files/caches" + (f" ({', '.join(removed)})" if removed else ""))


if args.fresh:
    clear_generated_run_state(run_dir)
else:
    print("Resume/default mode: preserving existing run artifacts; use --fresh to clear")

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
search_plan_path = run_dir / "search_plan.json"
sources_path = DATA_DIR / "sources.json"

print(f"[3/6] Generating search plan...")
result = safe_run(
    [
        "python3.12", str(SCRIPTS_DIR / "fetch_articles.py"),
        "--mode", args.mode,
        "--universe", str(universe_path),
        "--sources", str(sources_path),
        "--output", str(search_plan_path),
        "--date", run_date,
        "--plan-only",
    ],
    timeout=30, label="fetch_articles"
)
if result.returncode != 0:
    print("FATAL: Search plan generation failed. Refusing to continue with defaults.", file=sys.stderr)
    sys.exit(1)

# ═══════════════════════
# Stage 4: Summarize (agent writes articles.json, then summarize.py runs)
# ═══════════════════════
summary_path = run_dir / "summary.md"
print("[4/6] Summarizing articles...")
if not articles_path.exists():
    print(
        f"FATAL: {articles_path} is missing. Search plan was written to {search_plan_path}; "
        "populate articles.json with extracted fresh articles before summarizing. "
        "Refusing to create an empty article frame.",
        file=sys.stderr,
    )
    sys.exit(1)
result = safe_run(
    [
        "python3.12", str(SCRIPTS_DIR / "summarize.py"),
        "--input", str(articles_path),
        "--output", str(summary_path),
        "--mode", args.mode,
        "--date", run_date,
        "--max-hours", "72" if args.mode == "weekend" else "48",
    ],
    timeout=300, label="summarize"
)
if result.returncode != 0:
    print("FATAL: Summarizer failed. Refusing dashboard/deploy success.", file=sys.stderr)
    sys.exit(1)

# ═══════════════════════
# Stage 5: Build Dashboard
# ═══════════════════════
dashboard_path = run_dir / "dashboard.html"
print("[5/6] Building dashboard...")
result = safe_run(
    [
        "python3.12", str(SCRIPTS_DIR / "build_dashboard.py"),
        "--input", str(articles_path),
        "--summary", str(run_dir / "briefing.md"),
        "--output", str(dashboard_path),
        "--mode", args.mode,
        "--date", run_date,
    ],
    timeout=120, label="dashboard"
)
if result.returncode != 0:
    print("ERROR: Dashboard build failed.", file=sys.stderr)
    print("Skipping deploy — dashboard is required.", file=sys.stderr)
    sys.exit(1)

print("[5b/7] Validating run artifacts before deploy/reporting success...")
result = safe_run(
    [
        "python3.12", str(SCRIPTS_DIR / "validate_run.py"),
        "--run-dir", str(run_dir),
        "--mode", args.mode,
        "--date", run_date,
    ],
    timeout=60, label="validate_run",
)
if result.returncode != 0:
    print("FATAL: Run artifact validation failed. Refusing deploy/final success.", file=sys.stderr)
    sys.exit(1)

# ═══════════════════════
# Stage 6: Deploy to GitHub Pages
# ═══════════════════════
if args.skip_deploy:
    print("[6/7] Deploy: SKIPPED (--skip-deploy)")
else:
    print("[6/7] Deploying to GitHub + GitHub Pages...")
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
# Stage 7: Temporal Reasoning Consolidation (PRE-MARKET ONLY)
# ═══════════════════════
if args.mode == "pre-market":
    print("[7/7] Running temporal reasoning consolidation...")
    result = safe_run(
        [
            "python3.12", str(SCRIPTS_DIR / "reasoning_consolidate.py"),
            "--date", run_date,
        ],
        timeout=120, label="reasoning_consolidate"
    )
    if result.returncode != 0:
        print("WARNING: Temporal reasoning consolidation failed. Temporal brief NOT generated.", file=sys.stderr)
        print("  → Check runs/{prev_date}/daily/temporal_brief.md", file=sys.stderr)
else:
    if args.mode == "post-market":
        print("[7/7] Temporal reasoning: skipped (post-market — consolidation runs after next pre-market)")
    elif args.mode == "weekend":
        print("[7/7] Temporal reasoning: skipped (weekend mode)")
    else:
        print(f"[7/7] Temporal reasoning: skipped (mode={args.mode})")

# ═══════════════════════
# Complete
# ═══════════════════════
print()
print("=== Pipeline Complete ===")
print(f"Summary:  {summary_path}")
print(f"Dashboard: {dashboard_path}")
print(f"Articles: {articles_path}")
print(f"GH Pages: {PAGES_URL if 'PAGES_URL' in dir() else 'https://zeusnightbolt.github.io/BoltNews/'}")
if args.mode == "pre-market":
    yesterday = date.fromisoformat(run_date) - timedelta(days=1)
    brief_path = RUNS_DIR / yesterday.isoformat() / "daily" / "temporal_brief.md"
    print(f"Temporal Brief: {brief_path}")
