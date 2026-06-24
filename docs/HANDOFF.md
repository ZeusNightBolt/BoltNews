# BoltNews — Complete Handoff & Customization Guide

**Last updated:** 2026-06-24  
**Repo:** https://github.com/ZeusNightBolt/BoltNews  
**Live:** https://zeusnightbolt.github.io/BoltNews/  
**Local checkout:** `~/repos/BoltNews`  
**Hermes-OS project:** `~/.hermes/os/projects/boltnews`

---

## 1. What BoltNews Is

A fully autonomous daily news intelligence pipeline that sources, extracts, synthesizes, and deploys cross-asset market briefings — without any human intervention. It runs on a schedule (6 AM, 6 PM ET weekdays; 10 AM Sunday; 8 PM Friday weekly rollup) via Hermes cron jobs.

**Core principle:** This is NOT a headline aggregator. Every run must perform deep article extraction (full text, not snippets), synthesize findings into a research-analyst-grade briefing, and validate deterministically before deploying.

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    CRON SCHEDULER                           │
│  6AM Pre-Market │ 6PM Post-Market │ Sun 10AM │ Fri 8PM     │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  run_pipeline.py — Master Orchestrator                      │
│  • Auto-detects mode (pre/post/weekend)                     │
│  • Coordinates 8 stages                                     │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
   ┌──────────┬──────────┬──────────┬──────────┬─────────────┐
   │ Stage 1  │ Stage 2  │ Stage 3  │ Stage 4  │ Stages 5-8  │
   │ Universe │ Search   │ Article  │ Deep     │ Synthesize  │
   │ Build    │ Plan     │ Discovery│ Extract  │ + Validate  │
   │ (weekly) │ 50/15    │ (SearXNG)│ (10-15   │ + Deploy    │
   │          │ queries  │          │ articles)│ + Deliver   │
   └──────────┴──────────┴──────────┴──────────┴─────────────┘
                           ▼
   ┌──────────────────────────────────────────────────────────┐
   │  validate_run.py — Deterministic Guardrail               │
   │  Checks: articles.json not empty/search-plan-shaped,     │
   │  briefing.md has required sections, dashboard.html okay  │
   └──────────────────────────────────────────────────────────┘
                           ▼
   ┌──────────────────────────────────────────────────────────┐
   │  deploy.py → gh-pages branch → GitHub Pages              │
   │  reasoning_consolidate.py → temporal_brief.md (after AM) │
   └──────────────────────────────────────────────────────────┘
```

### Key Scripts (12 files, 4,329 lines total)

| Script | Lines | Purpose |
|--------|-------|---------|
| `run_pipeline.py` | 337 | Master orchestrator — mode detection, stage sequencing |
| `fetch_articles.py` | 496 | Search plan generator with date-constrained queries |
| `summarize.py` | 363 | Dedup + categorize + summarize articles |
| `build_dashboard.py` | 636 | Self-contained HTML dashboard |
| `deploy.py` | 524 | Push to GitHub + gh-pages, fail-closed on bad data |
| `validate_run.py` | 264 | Pre-deploy guardrail: rejects bad/missing artifacts |
| `market_snapshot.py` | 143 | Live market data validation (prevents hallucinated rallies) |
| `session_logic.py` | 195 | Wall Street session window enforcement |
| `weekly_rollup.py` | 346 | Friday aggregation across all weekday runs |
| `reasoning_consolidate.py` | 904 | Temporal reasoning: cross-run data diff engine |
| `build_universe.py` | 121 | Weekly VTI ticker universe builder |
| `scraper/` | — | Per-source scrapers (webkit, bot-detection bypass) |

### Data Flow

```
148 tickers (VTI >$5B, top 15% dollar vol)
  → 50 ticker queries + 15 topic queries (all date-suffixed)
  → SearXNG search (or web_search fallback)
  → Deep extraction: web_extract() + browser_navigate() for paywalls
  → Recency filter: 3-layer defense (query → keyword → agent instruction)
  → Synthesis: Executive Summary + Cross-Asset Matrix + Contrarian Flags
  → Validate → Deploy → Deliver to Telegram
```

## 3. Complete Setup Guide (recreate on another Hermes agent)

### Prerequisites

```bash
# Required tools
python3.12 (with duckdb, pandas, numpy)
SearXNG (or alternative search backend at localhost:8888)
Firefox BiDi (for paywalled site scraping)
GitHub account with Pages enabled
Hermes Agent with cron scheduler
```

### Step 1: Clone and Initialize

```bash
git clone https://github.com/ZeusNightBolt/BoltNews.git ~/repos/BoltNews
cd ~/repos/BoltNews
mkdir -p runs data docs dashboard logs
cp data/sources.json.example data/sources.json  # create if needed
```

### Step 2: Configure Environment

```bash
# ~/.hermes/.env
SEARXNG_URL=http://localhost:8888
GITHUB_TOKEN=ghp_...     # for gh-pages push
OPENROUTER_API_KEY=...   # or DEEPSEEK_API_KEY for LLM synthesis
```

### Step 3: Set Up SearXNG

```bash
# Install SearXNG (if not already running)
git clone https://github.com/searxng/searxng ~/searxng
cd ~/searxng
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# Edit searx/settings.yml: add 'json' to formats, configure engines
python -m searx.webapp &
# Verify: curl "http://localhost:8888/search?q=test&format=json"
```

### Step 4: Configure Cron Jobs

Create these 4 cron jobs via Hermes:

```bash
# 1. Pre-Market (6:00 AM ET, Mon-Fri)
hermes cron create "0 6 * * 1-5" \
  --name "BoltNews Pre-Market" \
  --prompt "Run the BoltNews PRE-MARKET pipeline..." \
  --skills boltnews-pipeline,github-pages-deploy \
  --model deepseek-v4-pro \
  --provider deepseek \
  --deliver telegram:7198242672

# 2. Post-Market (6:00 PM ET, Mon-Fri)
hermes cron create "0 18 * * 1-5" \
  --name "BoltNews Post-Market" \
  --prompt "Run the BoltNews POST-MARKET pipeline..." \
  --skills boltnews-pipeline,github-pages-deploy \
  --model deepseek-v4-pro \
  --provider deepseek \
  --deliver telegram:7198242672

# 3. Weekly Rollup (8:00 PM ET, Friday)
hermes cron create "0 20 * * 5" \
  --name "BoltNews Weekly Rollup" \
  --prompt "Run the BoltNews WEEKLY ROLLUP..." \
  --skills boltnews-pipeline,github-pages-deploy \
  --model deepseek-v4-pro \
  --provider deepseek \
  --deliver telegram:7198242672

# 4. Weekend (10:00 AM ET, Sunday)
hermes cron create "0 10 * * 0" \
  --name "BoltNews Weekend" \
  --prompt "Run the BoltNews WEEKEND pipeline..." \
  --skills boltnews-pipeline,github-pages-deploy \
  --deliver telegram:7198242672
```

### Step 5: Configure GitHub Pages

```bash
cd ~/repos/BoltNews
# Ensure gh-pages branch exists
git checkout -b gh-pages
git push origin gh-pages
# In GitHub repo Settings → Pages: set source to gh-pages branch, / (root)
# Add .nojekyll to root
touch .nojekyll && git add .nojekyll && git commit -m "Add .nojekyll" && git push
```

### Step 6: Verify End-to-End

```bash
# Run a manual pipeline test
cd ~/repos/BoltNews
python3.12 scripts/run_pipeline.py --mode pre-market --date $(date +%Y-%m-%d)

# Check output
ls runs/$(date +%Y-%m-%d)/pre-market/
# Should contain: search_plan.json, articles.json, briefing.md, summary.md

# Verify dashboard
curl https://zeusnightbolt.github.io/BoltNews/
```

### Step 7: Register with Hermes-OS

```bash
cd ~/.hermes
python3 skills/hermes-os/scripts/project_manager.py create \
  --name boltnews \
  --objective "Daily multi-agent financial news intelligence pipeline"

# Copy project files to Hermes-OS
cp ~/repos/BoltNews/README.md os/projects/boltnews/
cp ~/repos/BoltNews/docs/*.md os/projects/boltnews/docs/

# Rebuild indexes
python3 skills/hermes-os/scripts/project_manager.py rebuild-registry
python3 skills/hermes-os/scripts/index_builder.py rebuild
```

## 4. Handoff Checklist (quick-start for another agent)

1. **Clone**: `git clone https://github.com/ZeusNightBolt/BoltNews.git ~/repos/BoltNews`
2. **Deps**: `python3.12 -m pip install duckdb pandas numpy` + SearXNG running at :8888
3. **Env**: Set `SEARXNG_URL`, `GITHUB_TOKEN`, `OPENROUTER_API_KEY` in `~/.hermes/.env`
4. **Crons**: Create 4 jobs (see Step 4 above) — use `boltnews-pipeline` + `github-pages-deploy` skills
5. **Test**: `python3.12 scripts/run_pipeline.py --mode pre-market`
6. **Verify**: Check `runs/YYYY-MM-DD/pre-market/briefing.md` exists and is substantive
7. **Register**: `project_manager.py create --name boltnews` then `index_builder.py rebuild`

## 5. Common Failure Modes & Fixes

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| Dashboard shows links-only (no synthesis) | LLM skipped deep extraction | Force `web_extract()` on 10-15 article URLs before synthesis |
| Briefing claims "broad rally" when S&P fell | No market data validation | Run `market_snapshot.py` before validate; check `market_snapshot.json` |
| Articles from 3 weeks ago appear in "today's" briefing | Recency filter not applied | Check `STALE_INDICATORS` in `fetch_articles.py`; suffix all queries with date |
| SearXNG returns 0 results | All engines suspended (CAPTCHA) | `kill $(pgrep -f searx.webapp)` then restart |
| `articles.json` is search-plan-shaped (not articles) | Pipeline deleted artifacts mid-run | Use `--resume`; never delete `articles.json` after successful Stage 3 |
| PM and AM briefings contradict each other | Old `consolidate_daily.py` concatenation | Use `reasoning_consolidate.py` for temporal diff |
| GitHub Pages shows 404 for data files | Missing `.nojekyll` | Add `touch .nojekyll` to gh-pages root |
| Dashboard heading navigation broken | No TOC generation | Run `build_dashboard.py` — generates TOC from `##`/`###` headings |

## 6. Customization: Adapting BoltNews for Non-Financial Topics

*These are suggestions only — do NOT implement. They demonstrate how the BoltNews architecture generalizes beyond stock markets.*

### A. Technology / AI Industry Monitor

**Universe:** Top 50 AI/tech companies (Apple, Google, Microsoft, OpenAI, Anthropic, Meta, NVIDIA, etc.)  
**Sources:** TechCrunch, The Verge, Ars Technica, Hacker News, r/MachineLearning, ArXiv, GitHub trending  
**Queries:** Product launches, funding rounds, research papers, regulation, open-source releases, talent moves  
**Synthesis sections:** Executive Summary, Product/Launch Radar, Research Breakthroughs, Funding/M&A, Regulatory Watch, Talent Market  
**Cron:** Daily at 8 AM — cover overnight developments in AI

### B. Geopolitics / Policy Intelligence

**Universe:** Country/region based — US, EU, China, India, Middle East, Russia/Ukraine  
**Sources:** Reuters World, AP, CFR, CSIS, RAND, Diplomat, Foreign Affairs, Congressional Record  
**Queries:** Sanctions, trade policy, military movements, elections, diplomatic summits, energy security  
**Synthesis sections:** Executive Summary, Hot Zones (active conflicts), Diplomatic Calendar, Sanctions/Trade Radar, Energy Security, Election Watch  
**Cron:** Weekdays at 7 AM and 7 PM

### C. Healthcare / Biotech Pipeline

**Universe:** Top 100 biotech/pharma companies, FDA calendar, clinical trial registries  
**Sources:** FDA.gov, ClinicalTrials.gov, PubMed, STAT News, FierceBiotech, Endpoints News, BioPharma Dive  
**Queries:** Drug approvals, trial results, M&A, patent expirations, manufacturing disruptions, pricing reform  
**Synthesis sections:** Pipeline Radar (Phase 2/3 updates), FDA Calendar (upcoming decisions), M&A Watch, Patent Cliff, Regulatory/Legislative, Manufacturing  
**Cron:** Weekly (Sunday night) + event-driven (FDA decision days)

### D. Energy / Commodities Intelligence

**Universe:** Crude oil, natural gas, copper, lithium, uranium, agricultural commodities  
**Sources:** EIA.gov, IEA, OPEC, OilPrice.com, S&P Global Platts, Reuters Commodities, Weather.gov  
**Queries:** Supply disruptions, inventory reports, weather events, geopolitical outages, demand forecasts  
**Synthesis sections:** Supply/Demand Balance, Inventory Watch, Weather Impact, Geopolitical Risk, Price Action, Forward Curve  
**Cron:** Daily at 6 AM — before market open

### E. General Architecture Pattern (copy this template)

For ANY domain, the BoltNews architecture generalizes as:

```
┌──────────────────────────────────────────────────────────────┐
│  1. UNIVERSE DEFINITION                                     │
│     What entities/topics are we tracking? Define a list.    │
│     Can be dynamic (e.g., top N by metric) or static.       │
├──────────────────────────────────────────────────────────────┤
│  2. SOURCE STRATEGY                                         │
│     Identify 10-40 authoritative primary sources.           │
│     Mix: newswires, official data, forums, research.        │
│     Tag each source with extraction method.                 │
├──────────────────────────────────────────────────────────────┤
│  3. QUERY TEMPLATES                                         │
│     Design 5-15 topic queries + entity-specific queries.    │
│     Always suffix with date for recency.                    │
│     Rotate queries to avoid search engine fatigue.          │
├──────────────────────────────────────────────────────────────┤
│  4. DEEP EXTRACTION (the differentiator)                    │
│     Don't rely on snippets — pull full article text.        │
│     Use web_extract() for open sites, browser for paywalls. │
│     Extract specific data points, not vague summaries.      │
├──────────────────────────────────────────────────────────────┤
│  5. RECENCY ENFORCEMENT                                     │
│     Query layer: date suffix on every search                │
│     Keyword layer: reject "last month", "Q1", prior year    │
│     Agent layer: explicit instruction + time window         │
├──────────────────────────────────────────────────────────────┤
│  6. SYNTHESIS TEMPLATE                                      │
│     Executive Summary (3-5 sentences)                       │
│     Category sections with specific extracted data          │
│     Cross-category matrix showing connections               │
│     Contrarian flags: what's being ignored?                 │
│     Format rules: numbers > adjectives, source attribution  │
├──────────────────────────────────────────────────────────────┤
│  7. VALIDATION + DEPLOY                                     │
│     Deterministic checks before publishing                  │
│     Deploy to static site (GitHub Pages, Netlify, Vercel)   │
│     Auto-deliver to messaging platform (Telegram, Slack)    │
└──────────────────────────────────────────────────────────────┘
```

### F. Key Design Decisions for Any New Domain

1. **Universe size matters**: Stock markets have 148 tickers. A niche domain might need only 20 entities. A broad domain (all of tech) might need 200. Calibrate the search plan accordingly — don't drown in articles.

2. **Cadence is domain-dependent**: Markets need 2x/day (pre/post market). Policy needs 1x/day. Clinical trials need 1x/week. Match the schedule to the natural information flow of the domain.

3. **Recency window varies**: Markets = 24 hours. Tech = 48 hours. Policy = 72 hours (weekend news matters). Clinical trials = 7 days (papers publish weekly).

4. **Source strategy is the hardest part**: Finding and maintaining 40 reliable sources per domain takes months. Start with 10 and expand. Test each source for extraction reliability before adding it to the pipeline.

5. **Validation is domain-specific**: Markets validate against prices (deterministic). Policy validates against official statements (attribution). Tech validates against company blogs/GitHub (primary sources). Design validation rules BEFORE launching the pipeline.

6. **The synthesis template IS the product**: Spend time designing what the final output looks like. The sections, the tone, the data density. This is what users actually read. Everything else is plumbing.

## 7. GitHub Repo Update Notes (June 2026)

**Recent fixes deployed to live:**

| Date | Fix | Description |
|------|-----|-------------|
| Jun 16 | Session validation | Added `session_logic.py` + `market_snapshot.py` to prevent hallucinated market directions |
| Jun 14 | Recency hardening | 3-layer defense against stale articles contaminating briefings |
| Jun 9 | Temporal reasoning | Replaced concatenation with structured cross-run data diff engine |
| Jun 4 | Weekend hardening | Added `validate_run.py` guardrail; 72h recency window for Sunday runs |
| May 31 | Pipeline stabilization | Fixed artifact deletion bug; added `--resume` support |

**Repo state:** Active, 12 scripts, 4,329 lines of Python. 26 run directories (daily pre/post-market since May 30). Weekly rollups since June 5. Live dashboard at zeusnightbolt.github.io/BoltNews/.
