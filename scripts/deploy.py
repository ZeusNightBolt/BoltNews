#!/usr/bin/env python3.12
"""
BoltNews — Deploy to GitHub + GitHub Pages.
Pushes run data to main branch, dashboard.html to gh-pages as index.html.
CRITICAL: Reads GITHUB_TOKEN from ~/.hermes/.env (not env var — cron jobs have no env).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import date
from html import escape
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPO_OWNER = "ZeusNightBolt"
REPO_NAME = "BoltNews"
PAGES_URL = f"https://{REPO_OWNER}.github.io/{REPO_NAME}/"


ARCHIVE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>BoltNews — Archive</title>
<style>
  :root {{
    --bg: #0d1117; --bg-secondary: #161b22; --bg-tertiary: #21262d;
    --border: #30363d; --text: #c9d1d9; --text-muted: #8b949e;
    --accent: #58a6ff; --accent-emphasis: #1f6feb; --green: #3fb950;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.6; min-height: 100dvh;
  }}
  .container {{ max-width: 920px; margin: 0 auto; padding: 20px 24px; }}
  .navbar {{
    position: sticky; top: 0; z-index: 10; display: flex; align-items: center;
    justify-content: space-between; gap: 14px; margin-bottom: 22px; padding: 10px 0 12px;
    background: linear-gradient(180deg, rgba(13,17,23,0.98), rgba(13,17,23,0.90));
    backdrop-filter: blur(10px); border-bottom: 1px solid var(--border);
  }}
  .brand-mark {{ color: var(--text); font-weight: 700; text-decoration: none; }}
  .nav-links {{ display: inline-flex; align-items: center; gap: 8px; }}
  .nav-item {{ color: var(--text-muted); border: 1px solid transparent; border-radius: 999px; padding: 5px 12px; font-size: 0.82rem; text-decoration: none; }}
  .nav-item:hover {{ color: var(--text); background: var(--bg-secondary); border-color: var(--border); text-decoration: none; }}
  .nav-item.active {{ color: #fff; background: var(--accent-emphasis); }}
  .header {{
    border: 1px solid var(--border); border-radius: 14px; padding: 22px; margin-bottom: 24px;
    background: radial-gradient(circle at top left, rgba(88,166,255,0.14), transparent 34%), linear-gradient(180deg, rgba(22,27,34,0.95), rgba(13,17,23,0.95));
    box-shadow: 0 18px 48px rgba(1,4,9,0.28);
  }}
  h1 {{ font-size: 1.65rem; letter-spacing: -0.02em; }}
  .subtitle {{ color: var(--text-muted); margin-top: 4px; font-size: 0.9rem; }}
  .toolbar {{ display: flex; gap: 12px; align-items: center; margin: 18px 0 22px; }}
  .search-box {{ width: 100%; padding: 10px 12px; border: 1px solid var(--border); border-radius: 9px; background: var(--bg-secondary); color: var(--text); }}
  .run-card {{ border: 1px solid var(--border); border-radius: 12px; background: var(--bg-secondary); margin: 10px 0; overflow: hidden; }}
  .run-date {{ padding: 10px 14px; color: var(--text-muted); background: rgba(33,38,45,0.75); border-bottom: 1px solid var(--border); font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.08em; }}
  .run-links {{ display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 14px; }}
  .run-link {{ color: var(--accent); text-decoration: none; border: 1px solid var(--border); border-radius: 999px; padding: 6px 11px; background: var(--bg); font-size: 0.88rem; }}
  .run-link:hover {{ border-color: var(--accent); text-decoration: none; }}
  .footer {{ text-align: center; padding: 36px 0; color: var(--text-muted); font-size: 0.75rem; border-top: 1px solid var(--border); margin-top: 48px; }}
  .footer a {{ color: var(--accent); }}
  @media (max-width: 600px) {{ .container {{ padding: 12px 16px; }} .navbar {{ align-items: flex-start; flex-direction: column; }} .nav-links {{ flex-wrap: wrap; }} }}
</style>
</head>
<body>
<div class="container">
  <nav class="navbar" aria-label="BoltNews navigation">
    <a class="brand-mark" href="./index.html">⚡ BoltNews</a>
    <div class="nav-links">
      <a class="nav-item" href="./index.html">Latest</a>
      <a class="nav-item active" href="./archive.html">Archive</a>
      <a class="nav-item" href="https://github.com/ZeusNightBolt/BoltNews">GitHub</a>
    </div>
  </nav>
  <div class="header">
    <h1>📚 BoltNews Archive</h1>
    <div class="subtitle">Historical briefings served from GitHub Pages. Generated {generated_on}.</div>
  </div>
  <div class="toolbar"><input type="search" id="search" class="search-box" placeholder="Search date or briefing type..." oninput="searchArchive()"></div>
  <div id="archive-list">
    {archive_cards}
  </div>
  <div class="footer">BoltNews &copy; {year} &middot; <a href="https://github.com/ZeusNightBolt/BoltNews">GitHub</a></div>
</div>
<script>
function searchArchive() {{
  const q = document.getElementById('search').value.toLowerCase();
  document.querySelectorAll('.run-card').forEach(card => {{
    card.style.display = card.textContent.toLowerCase().includes(q) ? '' : 'none';
  }});
}}
</script>
</body>
</html>
"""


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


def build_archive_page(gh_pages_dir: Path) -> None:
    """Regenerate archive.html from files that actually exist on gh-pages."""
    mode_order = {"pre-market": 0, "post-market": 1, "weekend": 2}
    runs: dict[str, list[tuple[str, str]]] = {}
    for date_dir in gh_pages_dir.iterdir():
        if not date_dir.is_dir() or not re_fullmatch_date(date_dir.name):
            continue
        for page in date_dir.glob("*.html"):
            mode = page.stem
            if mode.endswith("-summary"):
                continue
            label = mode.replace("-", " ").title()
            runs.setdefault(date_dir.name, []).append((label, f"{date_dir.name}/{page.name}"))

    cards = []
    for run_date in sorted(runs, reverse=True):
        links = sorted(runs[run_date], key=lambda item: mode_order.get(item[0].lower().replace(" ", "-"), 99))
        links_html = "\n".join(
            f'<a class="run-link" href="{escape(href, quote=True)}">{escape(label)}</a>'
            for label, href in links
        )
        cards.append(
            f'<section class="run-card"><div class="run-date">{escape(run_date)}</div>'
            f'<div class="run-links">{links_html}</div></section>'
        )

    archive_html = ARCHIVE_TEMPLATE.format(
        generated_on=date.today().isoformat(),
        year=date.today().year,
        archive_cards="\n".join(cards) or '<p class="subtitle">No archived pages found.</p>',
    )
    (gh_pages_dir / "archive.html").write_text(archive_html)


def copy_file_if_exists(src: Path, dst: Path) -> bool:
    """Copy one file, creating parent dirs. Return True if copied."""
    if not src.exists() or not src.is_file():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def copy_tree_files(src_dir: Path, dst_dir: Path, suffixes: set[str] | None = None) -> list[str]:
    """Copy files from a tree without mutating while iterating over it."""
    copied: list[str] = []
    if not src_dir.exists():
        return copied
    files = [p for p in src_dir.rglob("*") if p.is_file()]
    for src in files:
        if suffixes and src.suffix not in suffixes:
            continue
        rel = src.relative_to(src_dir)
        dst = dst_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(str(rel))
    return copied


def html_listing(title: str, links: list[tuple[str, str]]) -> str:
    items = "\n".join(
        f'<li><a href="{escape(href, quote=True)}">{escape(label)}</a></li>'
        for label, href in links
    )
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>{escape(title)}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:#0d1117; color:#c9d1d9; line-height:1.6; margin:0; padding:24px; }}
a {{ color:#58a6ff; }}
.wrap {{ max-width:920px; margin:0 auto; }}
li {{ margin:8px 0; }}
.nav {{ margin-bottom:20px; }}
</style>
</head>
<body><main class="wrap"><div class="nav"><a href="../index.html">← Latest</a> · <a href="../archive.html">Archive</a></div><h1>{escape(title)}</h1><ul>{items}</ul></main></body>
</html>
'''


def propagate_indexes_and_files(gh_pages_dir: Path, run_dir: Path, mode: str, run_date: str) -> None:
    """Publish docs, project data, run artifacts, and machine-readable indexes to gh-pages."""
    docs_copied = copy_tree_files(PROJECT_ROOT / "docs", gh_pages_dir / "docs", suffixes={".md"})
    docs_links = [(rel, rel) for rel in sorted(docs_copied)]
    (gh_pages_dir / "docs" / "index.html").write_text(html_listing("BoltNews Docs", docs_links))

    project_data_dir = gh_pages_dir / "data" / "project"
    project_files = []
    for name in ["sources.json", "universe.json"]:
        if copy_file_if_exists(PROJECT_ROOT / "data" / name, project_data_dir / name):
            project_files.append(f"project/{name}")

    run_data_dir = gh_pages_dir / "data" / "runs" / run_date / mode
    run_files = []
    for name in ["briefing.md", "summary.md", "articles.json", "articles_enriched.json", "search_plan.json", "dashboard.html"]:
        if copy_file_if_exists(run_dir / name, run_data_dir / name):
            run_files.append(f"runs/{run_date}/{mode}/{name}")

    data_root = gh_pages_dir / "data"
    all_data_files = sorted(
        str(p.relative_to(data_root))
        for p in list(data_root.rglob("*"))
        if p.is_file() and p.name not in {"index.json", "index.html"}
    )
    index = {
        "generated_on": date.today().isoformat(),
        "latest": {"date": run_date, "mode": mode, "files": run_files},
        "project_files": project_files,
        "files": all_data_files,
    }
    (data_root / "index.json").write_text(json.dumps(index, indent=2))
    data_links = [(rel, rel) for rel in all_data_files]
    (data_root / "index.html").write_text(html_listing("BoltNews Data Index", data_links))


def re_fullmatch_date(value: str) -> bool:
    parts = value.split("-")
    return len(parts) == 3 and all(part.isdigit() for part in parts) and len(value) == 10


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

    html_text = dashboard_src.read_text(errors="replace")
    if "Executive Summary" not in html_text and "Cross-Asset" not in html_text:
        print(
            "ERROR: dashboard.html does not contain synthesized briefing markers "
            "(Executive Summary/Cross-Asset). Refusing to deploy link-only dashboard.",
            file=sys.stderr,
        )
        return False
    if html_text.count('class="source-link"') > 0 and html_text.count("<p>") < 8:
        print("ERROR: dashboard appears source-link dominated. Refusing deploy.", file=sys.stderr)
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
    for fname in ["briefing.md", "summary.md", "articles.json", "articles_enriched.json", "search_plan.json", "dashboard.html"]:
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

    # Backward-compatible path for any older archive links. The generated
    # archive below links to the compact YYYY-MM-DD/mode.html path, but copying
    # to runs/YYYY-MM-DD/mode.html keeps historical external links alive.
    pages_runs_dir = gh_pages_dir / "runs" / run_date
    pages_runs_dir.mkdir(parents=True, exist_ok=True)
    run(["cp", str(dashboard_src), str(pages_runs_dir / f"{mode}.html")])

    if summary_src.exists():
        run(["cp", str(summary_src), str(pages_date_dir / f"{mode}-summary.md")])

    propagate_indexes_and_files(gh_pages_dir, run_dir, mode, run_date)
    print("  [gh-pages] Propagated docs, data files, and index manifests")

    build_archive_page(gh_pages_dir)
    print("  [gh-pages] Regenerated archive.html from live page files")

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
