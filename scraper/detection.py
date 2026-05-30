"""
Protection detector. Classifies websites by anti-bot protection level.
Zero dependencies beyond stdlib. Used to route to the right extraction tier.
"""
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Literal

ProtectionLevel = Literal["none", "basic", "cloudflare", "akamai", "error"]

SIGNATURES: dict[str, list[tuple[str, str]]] = {
    "akamai": [
        ("header", r"(?i)X-Akamai-"),
        ("header", r"(?i)Server:\s*AkamaiGHost"),
        ("body", r"Reference\s+#\d+\.\d+"),
        ("body", r"Access Denied"),
    ],
    "cloudflare": [
        ("header", r"(?i)cf-ray:"),
        ("header", r"(?i)Server:\s*cloudflare"),
        ("body", r"cf-browser-verify"),
        ("body", r"Checking your browser before accessing"),
        ("body", r"cf-challenge"),
        ("body", r"Just a moment"),
    ],
    "basic": [
        ("status", r"403"),
        ("body", r"request could not be satisfied"),
        ("body", r"Request blocked"),
    ],
}

TIER_MAP: dict[ProtectionLevel, int] = {
    "none": 1,
    "basic": 2,
    "cloudflare": 3,
    "akamai": 3,
    "error": 3,
}


@dataclass
class DetectionResult:
    url: str
    level: ProtectionLevel = "none"
    status_code: int | None = None
    evidence: list[str] = field(default_factory=list)
    recommended_tier: int = 1


def detect(url: str, timeout: int = 8) -> DetectionResult:
    """Classify website protection level and recommend a scraping tier."""
    result = DetectionResult(url=url)

    try:
        proc = subprocess.run(
            [
                "curl", "-s",
                "-o", "/tmp/hermes_scraper_body.txt",
                "-w", "%{http_code}",
                "-D", "/tmp/hermes_scraper_headers.txt",
                "-A", "Mozilla/5.0 (X11; Linux x86_64; rv:150.0) Gecko/20100101 Firefox/150.0",
                "--max-time", str(timeout),
                "-L",
                url,
            ],
            capture_output=True, text=True, timeout=timeout + 3,
        )

        status_str = proc.stdout.strip()
        result.status_code = int(status_str) if status_str.isdigit() else None

        headers = ""
        body = ""
        try:
            with open("/tmp/hermes_scraper_headers.txt") as f:
                headers = f.read()
        except FileNotFoundError:
            pass
        try:
            with open("/tmp/hermes_scraper_body.txt") as f:
                body = f.read()
        except FileNotFoundError:
            pass

        # Check signatures in priority order (most severe first)
        for level in ["akamai", "cloudflare", "basic"]:
            for sig_type, pattern in SIGNATURES[level]:
                target = headers if sig_type in ("header", "status") else body[:10000]
                if re.search(pattern, target):
                    result.evidence.append(f"{level}:{sig_type}")
                    if level in ("akamai", "cloudflare"):
                        result.level = level  # type: ignore
                        break  # most severe, stop checking
                    elif level == "basic" and result.level == "none":
                        result.level = "basic"  # type: ignore
            if result.level in ("akamai", "cloudflare"):
                break

        # If HTTP 200 with no evidence, it's clean
        if result.status_code == 200 and not result.evidence:
            result.level = "none"

    except subprocess.TimeoutExpired:
        result.level = "error"
        result.evidence.append("curl_timeout")
    except Exception as e:
        result.level = "error"
        result.evidence.append(str(e)[:100])

    result.recommended_tier = TIER_MAP.get(result.level, 3)
    return result


def quick_detect(url: str) -> int:
    """Quick detection — returns recommended tier number only."""
    return detect(url, timeout=5).recommended_tier
