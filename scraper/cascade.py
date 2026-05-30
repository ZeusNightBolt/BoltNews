#!/usr/bin/env python3.12
"""
BoltNews Scraper — Main Cascade Orchestrator.
detect → extract → output. Clean API, no subprocess chains.

Usage:
    python3.12 cascade.py <URL> [--output result.json] [--force-tier 1|2|3] [--detect-only]

Programmatic:
    from scraper.cascade import scrape
    result = scrape("https://example.com")
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from .detection import detect, DetectionResult
from .extractors import (
    ExtractionResult,
    tier1_extract,
    tier2_extract,
    tier3_extract,
    extract_smart,
)
from .fox import is_fox_running


EXTRACTORS = {
    1: tier1_extract,
    2: tier2_extract,
    3: tier3_extract,
}


def scrape(url: str, force_tier: int | None = None) -> ExtractionResult:
    """
    Full cascade: detect protection → pick tier → extract.
    Falls through tiers on failure.

    Args:
        url: Target URL to scrape
        force_tier: Skip detection, use this tier (1, 2, or 3)

    Returns:
        ExtractionResult with .success, .title, .text, .html, .tier, .error
    """
    # Step 1: Detect
    if force_tier:
        start_tier = force_tier
        detection = DetectionResult(url=url, level="none", recommended_tier=force_tier)
    else:
        detection = detect(url, timeout=8)
        start_tier = detection.recommended_tier

    print(f"[Cascade] {url}", file=sys.stderr)
    print(f"  Protection: {detection.level} → starting Tier {start_tier}", file=sys.stderr)

    # Step 2: Extract, falling through tiers
    tiers_attempted = []
    result = ExtractionResult(url=url, tier=0, success=False)

    for tier in range(start_tier, 4):
        tiers_attempted.append(tier)
        print(f"  Trying Tier {tier}...", file=sys.stderr)

        if tier == 3 and is_fox_running():
            print(f"  Firefox already running — reusing session", file=sys.stderr)

        extractor = EXTRACTORS[tier]
        t_start = time.time()
        tier_result = extractor(url)
        elapsed = time.time() - t_start

        print(f"  Tier {tier}: {elapsed:.1f}s → {'SUCCESS' if tier_result.success else 'FAILED'} "
              f"({tier_result.text_length} chars)" + (
                  f" [{tier_result.error[:60]}]" if tier_result.error else ""
              ), file=sys.stderr)

        if tier_result.success:
            result = tier_result
            result.tier = tier
            result.success = True
            break

    if not result.success:
        result.error = f"All tiers exhausted ({tiers_attempted})"
        result.tier = tiers_attempted[-1] if tiers_attempted else 0

    return result


def batch_scrape(urls: list[str], force_tier: int | None = None,
                 max_concurrent: int = 1) -> list[ExtractionResult]:
    """Scrape multiple URLs sequentially with rate limiting."""
    from .behaviors import RateLimiter

    limiter = RateLimiter(max_pages=15, per_seconds=60)
    results = []

    for i, url in enumerate(urls):
        limiter.acquire()
        print(f"[Batch] {i+1}/{len(urls)}: {url[:80]}", file=sys.stderr)
        result = scrape(url, force_tier=force_tier)
        results.append(result)

        if result.tier == 3:
            time.sleep(2)  # Extra cooldown after browser scrapes

    return results


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="BoltNews Advanced Scraper — 3-tier cascade"
    )
    parser.add_argument("url", nargs="?", help="Target URL to scrape")
    parser.add_argument("--output", "-o", type=Path, help="Output JSON path")
    parser.add_argument("--force-tier", type=int, choices=[1, 2, 3],
                        help="Skip detection, use this tier")
    parser.add_argument("--detect-only", action="store_true",
                        help="Only detect protection level, don't scrape")
    parser.add_argument("--batch", type=Path,
                        help="Batch file: newline-separated URLs to scrape")
    args = parser.parse_args()

    if args.detect_only and args.url:
        result = detect(args.url)
        output = {
            "url": result.url,
            "level": result.level,
            "status_code": result.status_code,
            "evidence": result.evidence,
            "recommended_tier": result.recommended_tier,
        }
        print(json.dumps(output, indent=2))
        return

    if args.batch:
        urls = [line.strip() for line in args.batch.read_text().splitlines()
                if line.strip() and not line.startswith("#")]
        results = batch_scrape(urls, force_tier=args.force_tier)
        output = [
            {
                "url": r.url,
                "tier": r.tier,
                "success": r.success,
                "title": r.title,
                "text_length": r.text_length,
                "error": r.error,
                "text": r.text if r.success else None,
            }
            for r in results
        ]
    elif args.url:
        result = scrape(args.url, force_tier=args.force_tier)
        output = {
            "url": result.url,
            "tier": result.tier,
            "success": result.success,
            "title": result.title,
            "text_length": result.text_length,
            "error": result.error,
            "text": result.text if result.success else None,
            "html": result.html[:5000] if result.success else None,
            "blocked": result.blocked,
            "status_code": result.status_code,
        }
    else:
        parser.print_help()
        return

    # Output
    json_output = json.dumps(output, indent=2, default=str, ensure_ascii=False)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json_output)
        print(f"Saved: {args.output}", file=sys.stderr)

    print(json_output)


if __name__ == "__main__":
    main()
