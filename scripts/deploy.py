#!/usr/bin/env python3.12
"""
BoltNews — Deploy to GitHub + GitHub Pages.
Pushes run data (summary.md, articles.json, dashboard.html) to the BoltNews repo.
Deploys dashboard.html as index.html on gh-pages branch.
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
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO_URL = f"https://{REPO_OWNER}:{GITHUB_TOKEN}@github.com/{REPO_OWNER}/{REPO_NAME}.git"
PAGES_URL = f"https://{REPO_OWNER}.github.io/{REPO_NAME}/"


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run command and return result."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(cwd) if cwd else None)


def check_github_reachable() -> bool:
    """Quick connectivity check."""
    result = run(["curl", "-s", "--connect-timeout", "10", "https://github.com"], timeout=15)
    return result.returncode == 0


def deploy_run(run_dir: Path, mode: str, run_date: str):
    """Push run artifacts to GitHub and deploy to GH Pages."""
    
    if not GITHUB_TOKEN:
        print("ERROR: GITHUB_TOKEN not set. Skipping deploy.", file=sys.stderr)
        return False
    
    if not check_github_reachable():
        print("ERROR: GitHub unreachable. Skipping deploy.", file=sys.stderr)
        return False
    
    deploy_dir = Path("/tmp/boltnews-deploy")
    gh_pages_dir = Path("/tmp/boltnews-gh-pages")
    
    # Clean up
    run(["rm", "-rf", str(deploy_dir), str(gh_pages_dir)])
    
    # === Step 1: Clone main repo ===
    print("Cloning main repo...")
    result = run(["git", "clone", "--depth", "1", REPO_URL, str(deploy_dir)], timeout=60)
    if result.returncode != 0:
        print(f"ERROR cloning repo: {result.stderr[-500:]}", file=sys.stderr)
        return False
    
    # === Step 2: Copy run artifacts ===
    repo_run_dir = deploy_dir / "runs" / run_date / mode
    repo_run_dir.mkdir(parents=True, exist_ok=True)
    
    # Copy files
    for fname in ["summary.md", "articles.json", "articles_enriched.json", "dashboard.html"]:
        src = run_dir / fname
        if src.exists():
            run(["cp", str(src), str(repo_run_dir / fname)])
            print(f"  Copied: {fname}")
    
    # Also update the latest symlink
    latest_dir = deploy_dir / "runs" / "latest"
    run(["rm", "-rf", str(latest_dir)])
    run(["ln", "-s", str(repo_run_dir.relative_to(deploy_dir)), str(latest_dir)])
    
    # === Step 3: Commit and push main ===
    print("Committing to main...")
    run(["git", "add", "-A"], cwd=deploy_dir)
    result = run(
        ["git", "commit", "-m", f"BoltNews: {run_date} {mode} — {len(list(run_dir.glob('*')))} files"],
        cwd=deploy_dir
    )
    if "nothing to commit" in result.stdout + result.stderr:
        print("  No changes to commit")
    else:
        result = run(["git", "push", "origin", "main"], cwd=deploy_dir, timeout=120)
        if result.returncode != 0:
            print(f"ERROR pushing to main: {result.stderr[-500:]}", file=sys.stderr)
    
    # === Step 4: Deploy to gh-pages ===
    dashboard_src = run_dir / "dashboard.html"
    if not dashboard_src.exists():
        print("WARNING: No dashboard.html found. Skipping GH Pages deploy.", file=sys.stderr)
        return True
    
    print("Deploying to GitHub Pages...")
    result = run(
        ["git", "clone", "--depth", "1", "--branch", "gh-pages", REPO_URL, str(gh_pages_dir)],
        timeout=60
    )
    
    if result.returncode != 0:
        # gh-pages branch doesn't exist yet — create it
        print("  Creating gh-pages branch (first deploy)...")
        run(["git", "clone", "--depth", "1", REPO_URL, str(gh_pages_dir)], timeout=60)
        run(["git", "checkout", "--orphan", "gh-pages"], cwd=gh_pages_dir)
        run(["git", "rm", "-rf", "."], cwd=gh_pages_dir)
    
    # Copy dashboard as index.html
    run(["cp", str(dashboard_src), str(gh_pages_dir / "index.html")])
    
    # Also copy the latest dashboard to a dated directory
    pages_date_dir = gh_pages_dir / run_date
    pages_date_dir.mkdir(parents=True, exist_ok=True)
    run(["cp", str(dashboard_src), str(pages_date_dir / f"{mode}.html")])
    
    # Copy summary
    summary_src = run_dir / "summary.md"
    if summary_src.exists():
        run(["cp", str(summary_src), str(pages_date_dir / f"{mode}-summary.md")])
    
    # Commit and push gh-pages
    run(["git", "add", "-A"], cwd=gh_pages_dir)
    result = run(
        ["git", "commit", "-m", f"Deploy: {run_date} {mode}"],
        cwd=gh_pages_dir
    )
    
    if "nothing to commit" not in result.stdout + result.stderr:
        result = run(
            ["git", "push", "origin", "gh-pages", "--force"],
            cwd=gh_pages_dir, timeout=120
        )
        if result.returncode != 0:
            # Try without force
            result = run(
                ["git", "push", "origin", "gh-pages"],
                cwd=gh_pages_dir, timeout=120
            )
    
    print(f"✅ Deployed to: {PAGES_URL}")
    print(f"   Raw: https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/gh-pages/index.html")
    
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
        print(f"DRY RUN: Would deploy {args.run_dir} to {REPO_URL}")
        return
    
    success = deploy_run(args.run_dir, args.mode, args.date)
    
    if success:
        print("Deploy complete.")
    else:
        print("Deploy FAILED. Check logs above.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
