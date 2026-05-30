"""
Three-tier extractors: curl+readability, Camoufox, Firefox BiDi.
Each returns a standardized ExtractionResult.
"""
import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from .detection import detect
from .fox import FirefoxSession
from .behaviors import gaussian_dwell, scroll_chunked, RateLimiter


@dataclass
class ExtractionResult:
    url: str
    tier: int
    success: bool
    title: str = ""
    text: str = ""
    html: str = ""
    text_length: int = 0
    error: str = ""
    blocked: bool = False
    status_code: int | None = None


# ============================================================
# Tier 1: curl + readability-lxml
# ============================================================

def tier1_extract(url: str, timeout: int = 15) -> ExtractionResult:
    """Static extraction via curl + readability-lxml. Fast, no JS."""
    result = ExtractionResult(url=url, tier=1, success=False)

    try:
        # Try readability-lxml first (best extraction quality)
        import subprocess
        proc = subprocess.run(
            [
                "python3.12", "-c", f"""
import urllib.request
from readability import Document
from html2text import html2text

req = urllib.request.Request('{url}',
    headers={{'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}})
try:
    resp = urllib.request.urlopen(req, timeout=15)
    html = resp.read().decode('utf-8', errors='replace')
    result['status_code'] = resp.status
    doc = Document(html)
    title = doc.title()
    text = html2text(doc.summary())
    print(json.dumps({{"title": title, "text": text, "html": html[:50000], "status": resp.status}}))
except Exception as e:
    print(json.dumps({{"error": str(e)[:200]}}))
"""
            ],
            capture_output=True, text=True, timeout=timeout + 5,
        )

        if proc.returncode != 0:
            result.error = f"readability subprocess: {proc.stderr[:200]}"
            return result

        data = json.loads(proc.stdout.strip())
        if "error" in data:
            result.error = data["error"]
            return result

        result.title = data.get("title", "")
        result.text = data.get("text", "")
        result.html = data.get("html", "")
        result.text_length = len(result.text)
        result.status_code = data.get("status")
        result.success = result.text_length > 100  # Minimum viable content

        if not result.success:
            result.error = f"Content too short: {result.text_length} chars"

    except json.JSONDecodeError as e:
        result.error = f"JSON parse error: {e}"
    except Exception as e:
        result.error = f"Tier 1 extraction failed: {str(e)[:200]}"

    return result


# ============================================================
# Tier 2: Camoufox
# ============================================================

def tier2_extract(url: str, timeout: int = 30) -> ExtractionResult:
    """JS-rendered extraction via Camoufox headless browser."""
    result = ExtractionResult(url=url, tier=2, success=False)

    try:
        import subprocess
        proc = subprocess.run(
            [
                "python3.12", "-c", f"""
from camoufox import Camoufox
import time, json

try:
    with Camoufox(headless=True) as browser:
        page = browser.new_page()
        page.goto('{url}', timeout=20000)
        time.sleep(3)
        title = page.title()
        text = page.evaluate('document.body.innerText')
        html = page.content()
        print(json.dumps({{
            "title": title,
            "text": text[:100000],
            "html": html[:50000],
            "status": 200,
        }}))
except Exception as e:
    err = str(e)[:300]
    blocked = any(kw in err.lower() for kw in ['403', 'captcha', 'blocked', 'cloudflare', 'access denied'])
    print(json.dumps({{"error": err, "blocked": blocked}}))
"""
            ],
            capture_output=True, text=True, timeout=timeout + 10,
        )

        if proc.returncode != 0:
            result.error = f"Camoufox subprocess: {proc.stderr[:200]}"
            return result

        data = json.loads(proc.stdout.strip())
        if "error" in data:
            result.error = data["error"]
            result.blocked = data.get("blocked", False)
            return result

        result.title = data.get("title", "")
        result.text = data.get("text", "")
        result.html = data.get("html", "")
        result.text_length = len(result.text)
        result.status_code = data.get("status")
        result.success = result.text_length > 100

    except json.JSONDecodeError as e:
        result.error = f"JSON parse error: {e}"
    except Exception as e:
        result.error = f"Tier 2 extraction failed: {str(e)[:200]}"

    return result


# ============================================================
# Tier 3: Firefox WebDriver BiDi
# ============================================================

def tier3_extract(
    url: str,
    session: FirefoxSession | None = None,
    wait_s: float | None = None,
    timeout: int = 45,
) -> ExtractionResult:
    """Full browser extraction via Firefox BiDi. For anti-bot sites."""
    result = ExtractionResult(url=url, tier=3, success=False)

    own_session = session is None
    if own_session:
        session = FirefoxSession(headless=True)
        session.start()

    dwell = wait_s if wait_s is not None else gaussian_dwell(mu_s=8.0, sigma_s=2.0)

    try:
        from websockets.sync.client import connect

        with connect(session.ws_url, open_timeout=10) as ws:
            # Create session
            ws.send(json.dumps({
                "id": 1, "method": "session.new",
                "params": {"capabilities": {"alwaysMatch": {"acceptInsecureCerts": True}}}
            }))
            resp = json.loads(ws.recv())
            if "error" in resp:
                result.error = f"BiDi session error: {resp['error']}"
                return result
            session_id = resp["result"]["sessionId"]

            # Create tab
            ws.send(json.dumps({
                "id": 2, "method": "browsingContext.create",
                "params": {"type": "tab"}
            }))
            ctx = json.loads(ws.recv())["result"]["context"]

            # Navigate
            ws.send(json.dumps({
                "id": 3, "method": "browsingContext.navigate",
                "params": {"context": ctx, "url": url, "wait": "complete"}
            }))
            nav_resp = json.loads(ws.recv())
            if "error" in nav_resp:
                result.error = f"Navigation error: {nav_resp['error']}"
                return result

            landed_url = nav_resp["result"]["url"]

            # Human-like dwell + scroll
            time.sleep(dwell)
            scroll_amount = scroll_chunked()
            ws.send(json.dumps({
                "id": 4, "method": "script.evaluate",
                "params": {
                    "expression": f"window.scrollBy(0, {scroll_amount})",
                    "target": {"context": ctx},
                    "awaitPromise": False,
                }
            }))
            json.loads(ws.recv())  # consume scroll response
            time.sleep(dwell * 0.3)

            # Extract content
            ws.send(json.dumps({
                "id": 5, "method": "script.evaluate",
                "params": {
                    "expression": "document.title",
                    "target": {"context": ctx},
                    "awaitPromise": False,
                }
            }))
            title = json.loads(ws.recv())["result"]["result"]["value"]

            ws.send(json.dumps({
                "id": 6, "method": "script.evaluate",
                "params": {
                    "expression": "document.body.innerText",
                    "target": {"context": ctx},
                    "awaitPromise": False,
                }
            }))
            text = json.loads(ws.recv())["result"]["result"]["value"]

            ws.send(json.dumps({
                "id": 7, "method": "script.evaluate",
                "params": {
                    "expression": "document.documentElement.outerHTML",
                    "target": {"context": ctx},
                    "awaitPromise": False,
                }
            }))
            html = json.loads(ws.recv())["result"]["result"]["value"]

            # Close session
            ws.send(json.dumps({"id": 99, "method": "session.end", "params": {}}))
            json.loads(ws.recv())

            result.title = title or ""
            result.text = text or ""
            result.html = html or ""
            result.text_length = len(result.text)
            result.success = result.text_length > 100
            result.status_code = 200  # BiDi doesn't expose HTTP status directly

            if not result.success:
                result.error = f"Content too short: {result.text_length} chars"

    except ImportError:
        result.error = "websockets library not installed (pip install websockets)"
    except Exception as e:
        result.error = f"Tier 3 extraction failed: {str(e)[:300]}"
        result.blocked = any(kw in str(e).lower() for kw in [
            '403', 'captcha', 'blocked', 'cloudflare', 'access denied',
            'timeout', 'connection refused',
        ])
    finally:
        if own_session and session:
            session.stop()

    return result


# ============================================================
# Convenience: extract with auto-tier
# ============================================================

def extract_smart(url: str, preferred_tier: int | None = None) -> ExtractionResult:
    """Detect protection and extract using the appropriate tier."""
    if preferred_tier:
        tier = preferred_tier
    else:
        tier = detect(url, timeout=8).recommended_tier

    extractors = {
        1: lambda: tier1_extract(url),
        2: lambda: tier2_extract(url),
        3: lambda: tier3_extract(url),
    }

    result = extractors[tier]()

    # Fall through to higher tiers on failure
    while not result.success and tier < 3:
        tier += 1
        print(f"  Tier {tier-1} failed ({result.error[:80]}...), escalating to Tier {tier}")
        result = extractors[tier]()

    return result
