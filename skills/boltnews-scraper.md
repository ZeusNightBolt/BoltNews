---
name: boltnews-scraper
description: Unified advanced web scraping skill — 3-tier cascade (curl+readability → Camoufox → Firefox BiDi) with detection, anti-bot behaviors, and clean resource lifecycle. Built for BoltNews. Replaces fragmented web-scraping + loopnet-scraper patterns.
version: 1.0.0
author: Hermes Agent
metadata:
  hermes:
    tags: [scraping, anti-bot, bidi, firefox, camouflage, readability]
    category: data-science
---

# BoltNews Advanced Scraper

Clean, unified 3-tier web scraping cascade. Single module, no subprocess chains, proper resource management. Built from lessons learned maintaining the fragmented `web-scraping` and `loopnet-scraper` skills.

## Quick Start

```bash
# Full cascade: detect → extract
python3.12 ~/.hermes/os/projects/boltnews/scraper/cascade.py <URL> --output result.json

# Force specific tier
python3.12 ~/.hermes/os/projects/boltnews/scraper/cascade.py <URL> --force-tier 3

# Just detect protection level
python3.12 ~/.hermes/os/projects/boltnews/scraper/cascade.py <URL> --detect-only

# Programmatic (from agent — no subprocess)
python3.12 -c "
from scraper.cascade import scrape
result = scrape('https://example.com')
print(result.title, result.text[:200])
"
```

## Tiers

| Tier | Tool | When | Speed | Anti-Bot |
|------|------|------|-------|----------|
| 1 | curl + readability-lxml | Static HTML, blogs, news | Instant | None |
| 2 | Camoufox (headless) | JS-rendered, basic protection | ~5s | Fingerprint ev. |
| 3 | Firefox + WebDriver BiDi | Cloudflare, Akamai, paywalls | ~10s | Full browser |

## Detection Signatures

- **Cloudflare**: cf-ray header, cf-challenge, checking-your-browser
- **Akamai**: X-Akamai headers, Reference # pattern, Access Denied
- **Basic 403**: generic access denied
- **None**: HTTP 200 with no signatures

## Module Structure

```
scraper/
├── __init__.py
├── cascade.py       # Main orchestrator + scrape() API
├── detection.py     # Protection classifier
├── extractors.py    # T1 (curl+readability), T2 (Camoufox), T3 (BiDi)
├── fox.py           # Firefox BiDi session manager (context manager)
└── behaviors.py     # Human-like anti-detection behaviors
```

## Usage in BoltNews Pipeline

```python
from scraper.cascade import scrape

# For articles that need full text
result = scrape(article_url, force_tier=None)
if result.success:
    full_text = result.text
    title = result.title
```

## Pitfalls

- **Never start >1 Firefox BiDi session** (200-300MB each, OOM on 5.7GB system)
- **Always use context manager** for BiDi — `with FirefoxSession() as fox:` — ensures cleanup
- **Tier 1 first**: Most news sites don't need a browser. Don't waste resources.
- **Camoufox needs `headless=True`**: The default headless mode changed in newer versions
- **Detection before extraction**: Always classify first to avoid wasted attempts
