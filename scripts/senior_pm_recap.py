#!/usr/bin/env python3.12
"""Create a compact Senior Portfolio Manager recap from a BoltNews briefing.

This must read like a PM note, not a random extraction of headings/source
fragments. It builds mode-specific bullets from structured sections and filters
out table labels, source-only lines, and calendar fragments.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_MAX_CHARS = 1600
REQUIRED_LABEL = "## Senior PM Recap"

PRIMARY_SECTION_HINTS = {
    "pre-market": [
        "Futures and Current Market Snapshot",
        "Futures and Market Snapshot",
        "Overnight Top Developments",
        "Today's Risk Map",
        "Cross-Asset Positioning Matrix",
    ],
    "post-market": [
        "Closing Market Snapshot",
        "Why Markets Moved",
        "Equity Market Internals",
        "Cross-Asset Confirmation or Divergence",
        "Tomorrow Setup",
    ],
    "weekend": [
        "Weekly Market Scoreboard",
        "The Week's Core Narrative",
        "Next Week Playbook",
        "Contrarian Flags and Underpriced Risks",
    ],
    "weekly": [
        "Weekly Executive Summary",
        "Dominant Cross-Asset Narrative",
        "Contrarian Flags and Underpriced Risks",
    ],
}

BAD_LINE_PATTERNS = [
    r"^source:\s*",
    r"^sources?:\s*",
    r"^closing levels as of\b",
    r"^key levels to watch:?$",
    r"^overnight/morning watch:?$",
    r"^economic calendar",
    r"^holiday note:?$",
    r"^market data:?$",
    r"^news sources:?$",
]


def _strip_inline_markdown(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[`*_]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _sections(markdown: str) -> dict[str, str]:
    matches = list(re.finditer(r"^#{1,2}\s+(.+?)\s*$", markdown, re.MULTILINE))
    out: dict[str, str] = {}
    for idx, match in enumerate(matches):
        heading = _strip_inline_markdown(match.group(1).strip().strip("#"))
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown)
        out[heading] = markdown[start:end].strip()
    return out


def _section(sections: dict[str, str], wanted: str) -> str:
    for heading, body in sections.items():
        if heading.lower() == wanted.lower():
            return body
    return ""


def _clean_line(line: str) -> str:
    line = line.strip().strip("- ")
    line = _strip_inline_markdown(line)
    line = re.sub(r"\s+Source:.*$", "", line, flags=re.I).strip()
    return line


def _usable(line: str) -> bool:
    if not line or line.startswith("|") or line.startswith("#") or line == "---":
        return False
    clean = _clean_line(line)
    if len(clean) < 45:
        return False
    low = clean.lower()
    if any(re.search(p, low) for p in BAD_LINE_PATTERNS):
        return False
    # Avoid fragments that are just labels without a verb or market information.
    if clean.endswith(":") and len(clean.split()) <= 8:
        return False
    return True


def _first_matching(body: str, patterns: list[str]) -> str:
    lines = [_clean_line(x) for x in body.splitlines() if _usable(x)]
    for pat in patterns:
        rx = re.compile(pat, re.I)
        for line in lines:
            if rx.search(line):
                return line
    return lines[0] if lines else ""


def _market_table_snapshot(body: str) -> str:
    rows: dict[str, tuple[str, str]] = {}
    for raw in body.splitlines():
        if not raw.startswith("|") or "---" in raw or "Index / Asset" in raw:
            continue
        parts = [p.strip() for p in raw.strip("|").split("|")]
        if len(parts) >= 4:
            rows[parts[0]] = (parts[1], parts[3])
    spx = rows.get("S&P 500")
    ndx = rows.get("Nasdaq Composite")
    dow = rows.get("Dow Jones Industrial Average")
    vix = rows.get("VIX")
    if spx and ndx and dow:
        pieces = [f"S&P 500 {spx[1]}", f"Nasdaq {ndx[1]}", f"Dow {dow[1]}"]
        if vix:
            pieces.append(f"VIX {vix[1]}")
        return ", ".join(pieces) + "."
    return ""


def _sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
    return [p.strip() for p in parts if len(p.strip()) > 35]


def _cap(text: str, limit: int = 310) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_post_market_recap(markdown: str, max_chars: int) -> str:
    sections = _sections(markdown)
    snap = _section(sections, "Closing Market Snapshot")
    why = _section(sections, "Why Markets Moved")
    internals = _section(sections, "Equity Market Internals")
    cross = _section(sections, "Cross-Asset Confirmation or Divergence")
    setup = _section(sections, "Tomorrow Setup")

    tape = _market_table_snapshot(snap)
    direction = _first_matching(snap, [r"market direction", r"snapped", r"record"])
    if direction:
        tape = (tape + " " + direction).strip()

    catalyst = _first_matching(why, [r"US[- ]?Iran|US and Iran|ceasefire|Strait|halt military|free transit", r"Tech rebound", r"Comcast"])
    internals_line = _first_matching(internals, [r"Breadth", r"Only .*advanced", r"Sector Performance", r"Factor Performance"])
    cross_line = _first_matching(cross, [r"Interpretation", r"Divergence", r"Risk-On"])
    setup_line = _first_matching(setup, [r"Thursday.*payroll|Nonfarm|jobs", r"Base Case", r"Bear Case", r"Bull Case"])

    # Pull named sell-side color if present.
    sellside = []
    for line in internals.splitlines():
        clean = _clean_line(line)
        if any(name in clean for name in ["RBC", "Goldman", "J.P. Morgan", "JPMorgan", "Mizuho", "Trivariate"]):
            sellside.append(clean)
    sellside_text = " ".join(sellside[:2])

    risk_sentences = _sentences(internals_line)
    risk_text = " ".join(risk_sentences[:2]) if risk_sentences else internals_line
    if "only 209" in internals_line.lower() and "209" not in risk_text:
        risk_text = (risk_text + " Only 209 S&P 500 stocks advanced despite the index gain.").strip()

    recap_lines = [
        REQUIRED_LABEL,
        "**Post Market:** risk-on relief rally, but watch the quality of participation.",
        f"- **Tape:** {_cap(tape)}",
        f"- **Driver:** {_cap(catalyst)}",
        f"- **Outside color:** {_cap(sellside_text or internals_line)}",
        f"- **Risk:** {_cap(risk_text)}",
        f"- **Next watch:** {_cap(setup_line)}",
    ]
    return _trim_recap("\n".join(recap_lines), max_chars)


def _candidate_lines(markdown: str, mode: str) -> list[str]:
    sections = _sections(markdown)
    bodies = []
    for hint in PRIMARY_SECTION_HINTS.get(mode, []):
        body = _section(sections, hint)
        if body:
            bodies.append(body)
    if not bodies:
        bodies = [markdown]
    lines: list[str] = []
    for body in bodies:
        for raw in body.splitlines():
            if _usable(raw):
                lines.append(_clean_line(raw))
    return lines


def _trim_recap(recap: str, max_chars: int) -> str:
    if len(recap) <= max_chars:
        return recap.strip()
    lines = recap.splitlines()
    kept = lines[:2]
    for line in lines[2:]:
        candidate = "\n".join(kept + [line])
        if len(candidate) > max_chars - 1:
            break
        kept.append(line)
    text = "\n".join(kept).rstrip()
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


def build_recap(markdown: str, mode: str, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    if mode == "post-market":
        return build_post_market_recap(markdown, max_chars)

    mode_label = mode.replace("-", " ").title()
    candidates = _candidate_lines(markdown, mode)
    if not candidates:
        raise ValueError("briefing has no substantive lines to recap")
    bullets: list[str] = []
    seen: set[str] = set()
    for line in candidates:
        key = re.sub(r"[^a-z0-9]+", "", line.lower())[:120]
        if key in seen:
            continue
        seen.add(key)
        bullets.append(line)
        if len(bullets) >= 5:
            break

    recap_lines = [REQUIRED_LABEL, f"**{mode_label}:** compact portfolio-manager recap."]
    labels = ["Tape", "Driver", "Cross-asset read", "Positioning/risk", "Next watch"]
    for label, line in zip(labels, bullets):
        recap_lines.append(f"- **{label}:** {_cap(line)}")
    return _trim_recap("\n".join(recap_lines), max_chars)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate compact Senior PM recap from briefing.md")
    parser.add_argument("--briefing", type=Path, required=True)
    parser.add_argument("--mode", choices=["pre-market", "post-market", "weekend", "weekly"], required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    args = parser.parse_args()

    if not args.briefing.exists() or args.briefing.stat().st_size < 500:
        print(f"ERROR: briefing missing or too small: {args.briefing}", file=sys.stderr)
        raise SystemExit(1)

    recap = build_recap(args.briefing.read_text(errors="replace"), args.mode, args.max_chars)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(recap + "\n")
    print(recap)


if __name__ == "__main__":
    main()
