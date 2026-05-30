# BoltNews — Project Overview

**Objective:** Daily automated news intelligence pipeline for a fundamental long/short portfolio manager. Curates market-moving news across rates, FX, credit, equities, and derivatives. Filters out non-market noise (societal issues, ESG activism, etc.).

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│ Universe    │────▶│ Article      │────▶│ Dedup +      │
│ Builder     │     │ Fetcher      │     │ Summarizer   │
│ (weekly)    │     │ (daily 2x)   │     │              │
└─────────────┘     └──────────────┘     └──────────────┘
                                                 │
                    ┌──────────────┐              │
                    │ GitHub Pages │◀─────────────┤
                    │ Deploy       │              │
                    └──────────────┘     ┌──────────────┐
                                         │ Dashboard    │
                                         │ Builder      │
                                         └──────────────┘

┌─────────────┐
│ Weekly      │──▶ Friday 8PM ET rollup
│ Rollup      │
└─────────────┘
```

## Pipeline Stages

### 1. Universe Builder (`scripts/build_universe.py`)
- Reads VTI holdings from DuckDB `vti_daily_enriched_latest`
- Filters: market cap ≥ $5B, dollar volume > 0
- Ranks by dollar volume, takes top 15% (floor: 50 tickers)
- Supplements with generic market topics (SPX, Fed, rates, etc.)
- Output: `data/universe.json`

### 2. Article Fetcher (`scripts/fetch_articles.py`)
- Generates search plan from universe + sources
- Agent executes web_search queries for tickers and topics
- Filters articles by market relevance (blocked: social issues, ESG activism)
- Prioritizes: earnings, analyst actions, M&A, macro events
- Output: `runs/{date}/{mode}/articles.json`

### 3. Deduplication + Summarizer (`scripts/summarize.py`)
- Clusters similar articles by Jaccard word overlap (~35% threshold)
- Within clusters: keeps most detailed + contrasting views
- Categorizes into: Rates, FX, Credit, Equities, Derivatives, Macro, Regulatory
- Generates one-liner summaries (title + first sentence)
- Output: `runs/{date}/{mode}/summary.md`

### 4. Dashboard Builder (`scripts/build_dashboard.py`)
- Self-contained HTML with GitHub-dark theme
- Category tabs, search bar, article cards with ticker tags
- Mobile-responsive (Safari iOS compatible)
- Output: `runs/{date}/{mode}/dashboard.html`

### 5. Deploy (`scripts/deploy.py`)
- Pushes all artifacts to `ZeusNightBolt/BoltNews` main branch
- Deploys dashboard to `gh-pages` branch
- Archived at `https://zeusnightbolt.github.io/BoltNews/`

### 6. Weekly Rollup (`scripts/weekly_rollup.py`)
- Aggregates Mon-Fri summaries
- Identifies recurring themes via keyword frequency
- Output: `weekly/{YYYY-MM-DD}.md`

## Schedule

| Job | Time (ET) | Frequency | Cron |
|-----|-----------|-----------|------|
| Pre-Market | 6:00 AM | Weekdays | `boltnews-pre-market` |
| Post-Market | 6:00 PM | Weekdays | `boltnews-post-market` |
| Weekly Rollup | 8:00 PM | Fridays | `boltnews-weekly-rollup` |
| Universe Refresh | Monday pre-market | Weekly | (inline in pre-market) |

## Key Design Decisions

1. **Search-first, scrape-later**: web_search for discovery → web_extract for content → browser only for paywalled sources
2. **No paid APIs**: All free/public sources. SearXNG for search, curl+readability for extraction, Firefox BiDi for anti-bot sites
3. **Agent-driven execution**: Cron jobs run as agent sessions — the agent performs searches, extracts content, and composes summaries in real-time
4. **Stateless runs**: Each run starts fresh. Context comes from markdown files on disk, not session memory
5. **GitHub as source of truth**: All output pushed to GitHub. Cloud record. Reproducible.

## Filesystem

```
~/.hermes/os/projects/boltnews/
├── INDEX.md              # Auto-generated layer 1 index
├── PROJECT.md            # This file
├── docs/                 # Playbooks and methodology
├── scripts/              # Pipeline scripts (Python 3.12)
│   ├── run_pipeline.py   # Master orchestrator
│   ├── build_universe.py # Ticker universe builder
│   ├── fetch_articles.py # Search plan generator
│   ├── summarize.py      # Dedup + categorize + summarize
│   ├── build_dashboard.py# HTML dashboard builder
│   ├── deploy.py         # GitHub + GH Pages deploy
│   └── weekly_rollup.py  # Friday weekly aggregation
├── data/
│   ├── universe.json     # Filtered ticker watchlist
│   └── sources.json      # Seed + discovered news sources
├── runs/
│   └── YYYY-MM-DD/
│       ├── pre-market/
│       │   ├── articles.json
│       │   ├── articles_enriched.json
│       │   ├── summary.md
│       │   └── dashboard.html
│       └── post-market/
│           ├── articles.json
│           ├── articles_enriched.json
│           ├── summary.md
│           └── dashboard.html
└── weekly/
    └── YYYY-MM-DD.md     # Friday rollups
```

## GitHub

- **Repo**: `ZeusNightBolt/BoltNews`
- **Main branch**: Full project + run archives
- **gh-pages branch**: Dashboard deployments
- **Pages URL**: `https://zeusnightbolt.github.io/BoltNews/`
- **Raw access**: `https://raw.githubusercontent.com/ZeusNightBolt/BoltNews/main/runs/{date}/{mode}/summary.md`

## Dependencies

- Python 3.12 (system)
- DuckDB (for universe builder)
- Standard library + no external scraping deps (agent uses web_search/web_extract)
- Git + GitHub token (for deploy)
