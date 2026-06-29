#!/usr/bin/env python3.12
"""Deterministic Telegram delivery summary for BoltNews cron runs.

This script is intentionally separate from the LLM cron final response. Agent-mode
cron jobs have repeatedly produced verification prose instead of the Senior PM
recap despite prompt instructions. This script gives Hermes no_agent cron a
verbatim stdout payload: link first, then senior_pm_recap.md, then compact status.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PAGES_URL = "https://zeusnightbolt.github.io/BoltNews/"
MODE_TO_LABEL = {
    "pre-market": "Pre-market",
    "post-market": "Post-market",
    "weekend": "Weekend",
    "weekly": "Weekly rollup",
}


def ny_today() -> str:
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


def weekly_anchor_date() -> str:
    today = datetime.now(ZoneInfo("America/New_York")).date()
    # Friday = 4. If run later in the weekend, use the most recent Friday.
    days_since_friday = (today.weekday() - 4) % 7
    return (today - timedelta(days=days_since_friday)).isoformat()


def run_dir_for(mode: str, date_arg: str | None) -> tuple[str, Path]:
    date_str = date_arg or (weekly_anchor_date() if mode == "weekly" else ny_today())
    if mode == "weekly":
        # Current weekly artifact convention is weekly/YYYY-MM-DD.md plus optional
        # manually/generated recap. Keep support here, but scheduled weekly cron can
        # also point this script at a future senior_pm_recap.md if added.
        return date_str, PROJECT_ROOT / "weekly"
    return date_str, PROJECT_ROOT / "runs" / date_str / mode


def validate_run(mode: str, date_str: str, run_dir: Path) -> tuple[bool, str]:
    if mode == "weekly":
        note = run_dir / f"{date_str}.md"
        if note.exists() and note.stat().st_size > 1000:
            return True, f"weekly note present ({note.stat().st_size:,} bytes)"
        return False, f"weekly note missing or too small: {note}"

    cmd = [
        "python3.12",
        str(PROJECT_ROOT / "scripts" / "validate_run.py"),
        "--run-dir",
        str(run_dir),
        "--mode",
        mode,
        "--date",
        date_str,
    ]
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, text=True, capture_output=True, timeout=90)
    text = (proc.stdout + proc.stderr).strip().replace("\n", " ")
    return proc.returncode == 0, text or f"validate_run exit {proc.returncode}"


def recap_path_for(mode: str, date_str: str, run_dir: Path) -> Path:
    if mode == "weekly":
        return run_dir / f"{date_str}_senior_pm_recap.md"
    return run_dir / "senior_pm_recap.md"


def build_payload(mode: str, date_str: str, run_dir: Path) -> str:
    recap_path = recap_path_for(mode, date_str, run_dir)
    ok, validation = validate_run(mode, date_str, run_dir)

    if not recap_path.exists() or recap_path.stat().st_size < 50:
        return "\n".join(
            [
                PAGES_URL,
                "## Senior PM Recap",
                f"ERROR: {MODE_TO_LABEL.get(mode, mode)} recap missing or too small for {date_str}.",
                f"Expected: {recap_path}",
                f"Validation: {'OK' if ok else 'FAILED'} — {validation}",
            ]
        )

    recap = recap_path.read_text(encoding="utf-8", errors="replace").strip()
    if not recap.startswith("## Senior PM Recap"):
        return "\n".join(
            [
                PAGES_URL,
                "## Senior PM Recap",
                f"ERROR: recap file exists but does not start with required header: {recap_path}",
                f"Validation: {'OK' if ok else 'FAILED'} — {validation}",
            ]
        )

    status = [
        "",
        f"Status: {'validated' if ok else 'validation failed'} — {MODE_TO_LABEL.get(mode, mode)} {date_str}.",
        f"Run dir: {run_dir}",
        f"Validation: {validation}",
    ]
    return PAGES_URL + "\n\n" + recap + "\n" + "\n".join(status)


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit deterministic BoltNews Telegram summary")
    parser.add_argument("--mode", choices=["pre-market", "post-market", "weekend", "weekly"], required=True)
    parser.add_argument("--date", default=None, help="YYYY-MM-DD; defaults to NY today or weekly Friday anchor")
    args = parser.parse_args()

    date_str, run_dir = run_dir_for(args.mode, args.date)
    print(build_payload(args.mode, date_str, run_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
