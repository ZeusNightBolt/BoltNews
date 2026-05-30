#!/usr/bin/env python3.12
"""
BoltNews — Deploy to GitHub + GitHub Pages.
Pushes run data to main branch, dashboard.html to gh-pages as index.html.
CRITICAL: Reads GITHUB_TOKEN from ~/.hermes/.env (not env var — cron jobs have no env).
"""
import argparse
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPO_OWNER = "ZeusNightBolt"
REPO_NAME = "BoltNews"
PAGES_URL = f"https://{REPO_OWNER}.github.io/{REPO_NAME}/"


def get_github_token() -> str:
    """Read GITHUB_TOKEN from .env file. Cron jobs have no environment."""
    env_path = Path.home() / ".hermes" / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("GITHUB_TOKEN=") and not line.startswith("#"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def get_repo_url() -> str:
    token = get_github_token()
    if not token:
        return ""
    return f"https://{REPO_OWNER}:{token}@github.com/{REPO_OWNER}/{REPO_NAME}.git"


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 120, check: bool = False) -> subprocess.CompletedProcess:
    """Run command. If check=True, raise on non-zero exit."""
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=str(cwd) if cwd else None)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr[-500:]}")
    return result


def check_github_reachable() -> bool:
    result = run(["curl", "-s", "--connect-timeout", "10", "https://github.com"], timeout=15)
    return result.returncode == 0


def deploy_run(run_dir: Path, mode: str, run_date: str) -> bool:
    """Push run artifacts to GitHub main branch + deploy dashboard to gh-pages."""

    repo_url = get_repo_url()
    if not repo_url:
        print("ERROR: GITHUB_TOKEN not found in ~/.hermes/.env. Skipping deploy.", file=sys.stderr)
        return False

    if not check_github_reachable():
        print("ERROR: GitHub unreachable. Skipping deploy.", file=sys.stderr)
        return False

    # Verify required files exist
    dashboard_src = run_dir / "dashboard.html"
    summary_src = run_dir / "summary.md"
    articles_src = run_dir / "articles.json"

    if not dashboard_src.exists():
        print(f"ERROR: dashboard.html not found at {dashboard_src}. Cannot deploy.", file=sys.stderr)
        return False

    # ═══════════════════════════════════════════
    # RECENCY GATE: Verify articles are fresh before deploying
    # ═══════════════════════════════════════════
    max_hours = 48
    stale_warning = False
    try:
        with open(articles_src) as f:
            import json as _json
            data = _json.load(f)
        articles_list = data if isinstance(data, list) else data.get("articles", [])
        article_count = len(articles_list)
        if article_count == 0:
            print(f"WARNING: articles.json has 0 articles. Dashboard may be empty.", file=sys.stderr)
            stale_warning = True
        # Check for explicit age_hours on articles
        stale_count = sum(1 for a in articles_list 
                         if isinstance(a, dict) and a.get("age_hours", 0) 
                         and (isinstance(a["age_hours"], (int, float)) and a["age_hours"] > max_hours))
        if stale_count > 0:
            print(f"WARNING: {stale_count}/{article_count} articles are >{max_hours}h old. Deploying anyway.", file=sys.stderr)
            stale_warning = True
    except Exception:
        pass  # Can't read articles.json — proceed anyway
    # Note: stale_warning doesn't block deploy, but the flag is logged

    deploy_dir = Path("/tmp/boltnews-deploy")
    gh_pages_dir = Path("/tmp/boltnews-gh-pages")

    # Cleanup
    run(["rm", "-rf", str(deploy_dir), str(gh_pages_dir)])

    # ═══════════════════════════════════════════
    # STEP 1: Push run artifacts to main branch
    # ═══════════════════════════════════════════
    print("[deploy] Cloning main branch...")
    result = run(["git", "clone", "--depth", "1", repo_url, str(deploy_dir)], timeout=60)
    if result.returncode != 0:
        print(f"ERROR cloning repo: {result.stderr[-500:]}", file=sys.stderr)
        return False

    # Copy artifacts to dated directory
    repo_run_dir = deploy_dir / "runs" / run_date / mode
    repo_run_dir.mkdir(parents=True, exist_ok=True)

    files_copied = 0
    for fname in ["summary.md", "articles.json", "articles_enriched.json", "dashboard.html"]:
        src = run_dir / fname
        if src.exists():
            run(["cp", str(src), str(repo_run_dir / fname)])
            files_copied += 1
            print(f"  [main] Copied: {fname}")

    # Update latest symlink
    latest_dir = deploy_dir / "runs" / "latest"
    run(["rm", "-rf", str(latest_dir)])
    run(["ln", "-s", str(repo_run_dir.relative_to(deploy_dir)), str(latest_dir)])

    # Commit and push
    print("[deploy] Pushing to main...")
    run(["git", "add", "-A"], cwd=deploy_dir)
    result = run(
        ["git", "commit", "-m", f"BoltNews: {run_date} {mode} — {files_copied} files"],
        cwd=deploy_dir,
    )
    if "nothing to commit" not in result.stdout + result.stderr:
        result = run(["git", "push", "origin", "main"], cwd=deploy_dir, timeout=120)
        if result.returncode != 0:
            print(f"ERROR pushing main: {result.stderr[-500:]}", file=sys.stderr)
            # Don't return False — gh-pages deploy can still work
    else:
        print("  [main] No changes to commit")

    # ═══════════════════════════════════════════
    # STEP 2: Deploy dashboard to gh-pages
    # ═══════════════════════════════════════════
    print("[deploy] Deploying to GitHub Pages...")

    # Clone gh-pages branch
    result = run(
        ["git", "clone", "--depth", "1", "--branch", "gh-pages", repo_url, str(gh_pages_dir)],
        timeout=60,
    )

    if result.returncode != 0:
        # First deploy: gh-pages branch doesn't exist yet — create it
        print("  [gh-pages] Branch doesn't exist, creating...")
        run(["git", "clone", "--depth", "1", repo_url, str(gh_pages_dir)], timeout=60)
        run(["git", "checkout", "--orphan", "gh-pages"], cwd=gh_pages_dir)
        run(["git", "rm", "-rf", "."], cwd=gh_pages_dir, check=False)

    # Copy dashboard as index.html (this is what GH Pages serves)
    run(["cp", str(dashboard_src), str(gh_pages_dir / "index.html")])
    print(f"  [gh-pages] Copied dashboard → index.html ({dashboard_src.stat().st_size} bytes)")

    # Also archive to dated directory for record-keeping
    pages_date_dir = gh_pages_dir / run_date
    pages_date_dir.mkdir(parents=True, exist_ok=True)
    run(["cp", str(dashboard_src), str(pages_date_dir / f"{mode}.html")])

    if summary_src.exists():
        run(["cp", str(summary_src), str(pages_date_dir / f"{mode}-summary.md")])

    # Commit and FORCE push gh-pages (static assets only, force is safe)
    run(["git", "add", "-A"], cwd=gh_pages_dir)
    result = run(
        ["git", "commit", "-m", f"Deploy: {run_date} {mode}"],
        cwd=gh_pages_dir,
    )

    pushed = False
    if "nothing to commit" not in result.stdout + result.stderr:
        result = run(
            ["git", "push", "origin", "gh-pages", "--force"],
            cwd=gh_pages_dir, timeout=120,
        )
        if result.returncode == 0:
            pushed = True
        else:
            # Retry once without force
            print("  [gh-pages] Force push failed, retrying without --force...", file=sys.stderr)
            result = run(
                ["git", "push", "origin", "gh-pages"],
                cwd=gh_pages_dir, timeout=120,
            )
            pushed = result.returncode == 0
    else:
        pushed = True  # No changes needed — already up to date
        print("  [gh-pages] Already up to date")

    # Verify
    verify_url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/gh-pages/index.html"
    if pushed:
        print(f"✅ Deployed to: {PAGES_URL}")
        print(f"   Verify (raw): {verify_url}")
    else:
        print(f"❌ GH Pages push FAILED", file=sys.stderr)
        print(f"   Check: {verify_url}", file=sys.stderr)
        return False

    # Cleanup
    run(["rm", "-rf", str(deploy_dir), str(gh_pages_dir)])

    return True


def main():
    parser = argparse.ArgumentParser(description="BoltNews Deployer")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=["pre-market", "post-market", "weekend"], required=True)
    parser.add_argument("--date", type=str, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        print(f"DRY RUN: Would deploy {args.run_dir}")
        print(f"  Token present: {bool(get_github_token())}")
        print(f"  GitHub reachable: {check_github_reachable()}")
        return

    success = deploy_run(args.run_dir, args.mode, args.date)

    if success:
        print("[deploy] Deploy complete.")
    else:
        print("[deploy] Deploy FAILED.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
