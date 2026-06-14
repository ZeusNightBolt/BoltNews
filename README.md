# BoltNews — Cross-Asset News Briefing Pipeline

BoltNews is a daily automated market-intelligence pipeline for a fundamental long/short portfolio manager. It produces synthesized cross-asset research notes across equities, rates, credit, FX, commodities, volatility, and crypto — not headline dumps.

Live dashboard: https://zeusnightbolt.github.io/BoltNews/

Archive: https://zeusnightbolt.github.io/BoltNews/archive.html

Data index: https://zeusnightbolt.github.io/BoltNews/data/index.html

Docs index: https://zeusnightbolt.github.io/BoltNews/docs/index.html

## Current operating contract

The authoritative briefing artifact is:

```text
runs/{YYYY-MM-DD}/{mode}/briefing.md
```

`summary.md` is only an article/link digest and fallback input. The dashboard must render `briefing.md`; deploy refuses link-only dashboards missing synthesized briefing markers.

Every briefing must follow the canonical templates in `docs/briefing-template-spec.md` and every discovery run must use the multi-agent lane structure in `docs/multi-agent-news-flow.md`.

## Briefing modes and section order

### Pre-market

Purpose: answer "Where are markets now, what happened overnight, and what is today's setup?"

Required top sections:

1. `Futures and Current Market Snapshot`
2. `Overnight Top Developments`
3. `Global Session Recap`
4. `Macro, Rates, and Policy Setup`
5. `FX and Commodities`
6. `Equities and Single-Stock Watchlist`
7. `Sector and Factor Setup`
8. `Today's Risk Map`
9. `Source Notes and Data Quality`

### Post-market

Purpose: answer "What moved today, what changed, and what carries into tomorrow?"

Required top sections:

1. `Closing Market Snapshot`
2. `Why Markets Moved`
3. `Equity Market Internals`
4. `Rates, Macro, and Policy`
5. `Earnings and Corporate Developments`
6. `Cross-Asset Confirmation or Divergence`
7. `Tomorrow Setup`
8. `Source Notes and Data Quality`

### Weekend

Purpose: answer "What changed this week, what matters next week, and what risks are underpriced?"

Required top sections:

1. `Weekly Market Scoreboard`
2. `The Week's Core Narrative`
3. `Macro and Policy Review`
4. `Equity and Sector Review`
5. `Commodities, FX, Credit, and Volatility`
6. `Geopolitics and Event Risk`
7. `Next Week Playbook`
8. `Historical Context`
9. `Source Notes and Data Quality`

## Multi-agent discovery lanes

`scripts/fetch_articles.py --plan-only` writes `search_plan.json` with schema version 2.0. The plan includes mode-specific section order, weekday topic keywords, lane budgets, timeouts, verification gates, and a self-contained subagent handoff prompt.

Default lanes:

1. `market-snapshot` — futures/close, yields, DXY, oil, gold, vol, crypto.
2. `overnight-or-session-headlines` — overnight, session, or weekly top developments.
3. `macro-policy-rates-fx` — Fed, central banks, inflation, jobs, curve, dollar, FX.
4. `equities-earnings-single-stocks` — earnings, guidance, analyst actions, movers.
5. `commodities-credit-vol` — oil/gas/metals, credit, defaults/refinancing, options/vol.
6. `dedupe-validation-synthesis` — stale filtering, timestamp validation, dedupe, coverage checks, synthesis.

Timeout defaults:

- Global discovery budget: 1,800 seconds.
- Lane timeout: 300-480 seconds.
- Search timeout: 45 seconds/query.
- Extraction timeout: 75 seconds/URL.
- SearXNG backoff: `[3, 8, 20]` seconds.

## Pipeline stages

1. Universe build: `scripts/build_universe.py`
   - Reads VTI holdings from the local market-data warehouse.
   - Filters/liquidity-ranks names and writes `data/universe.json`.

2. Search-plan generation: `scripts/fetch_articles.py`
   - Generates mode/date/weekday-specific search plans and lane handoff context.
   - Writes `runs/{date}/{mode}/search_plan.json`.

3. Article discovery and extraction: agent lane execution
   - Executes query plan using web search and full-text extraction.
   - Rejects stale, headline-only, no-timestamp, and non-market records.
   - Writes `articles.json` and optionally `articles_enriched.json`.

4. Synthesis: `briefing.md`
   - Produces the formal research note in the canonical section order.
   - Numeric claims require source and timestamp/as-of context.
   - Missing required data is labeled `Data unavailable — <reason>`.

5. Dashboard build: `scripts/build_dashboard.py`
   - Renders `briefing.md` to static HTML.
   - Generates a heading-derived Table of Contents from `##`/`###` headings.
   - Verifies TOC anchors resolve locally.
   - Fails closed on missing, invalid, zero-article, or search-plan-shaped article feeds.

6. Deterministic run validation: `scripts/validate_run.py`
   - Blocks deploy/final success if required artifacts are missing, malformed, stale-plan-shaped, section-incomplete, or link-only.
   - Validates `search_plan.json`, `articles.json`, `briefing.md`, `summary.md`, and `dashboard.html` before cron can report success.

7. Deploy and propagation: `scripts/deploy.py`
   - Pushes run artifacts to `main`.
   - Pushes the static dashboard to `gh-pages`.

## GitHub Pages propagation

`scripts/deploy.py` is responsible for publishing not just the latest dashboard, but the audit trail and navigation indexes:

   - Regenerates `archive.html` from actual `gh-pages` files.
   - Propagates docs/data indexes and files:
     - `docs/*.md`
     - `docs/index.html`
     - `data/project/sources.json`
     - `data/project/universe.json`
     - `data/runs/{date}/{mode}/*`
     - `data/index.json`
     - `data/index.html`
   - Writes `.nojekyll` so GitHub Pages serves markdown/data files literally.

7. Temporal reasoning consolidation: `scripts/reasoning_consolidate.py`
   - Auto-triggered after pre-market runs.
   - Compares post-market vs pre-market data points.
   - Produces `temporal_brief.md` and `temporal_diff.json`.
   - Never revert to mechanical concatenation.

8. Weekly rollup: `scripts/weekly_rollup.py`
   - Aggregates week artifacts and temporal briefs.
   - Produces a weekly research synthesis.

## Cron jobs

| Job | ID | Schedule | Contract |
|---|---|---|---|
| BoltNews Pre-Market | `57148987bc98` | 6:00 AM ET Monday-Friday | Use `docs/briefing-template-spec.md`; start with futures/current market snapshot; write `briefing.md`; run `validate_run.py`; build/deploy/dashboard; auto-consolidate after run. |
| BoltNews Post-Market | `cffe38c452c9` | 6:00 PM ET Monday-Friday | Use post-market template; start with closing market snapshot; write `briefing.md`; run `validate_run.py`; build/deploy/dashboard. |
| BoltNews Weekend | `396458906931` | 10:00 AM ET Sunday | Use weekend template with 72h recency window; write weekend `briefing.md`; run `validate_run.py`; build/deploy/dashboard. |
| BoltNews Weekly Rollup | `949d2440242b` | 8:00 PM ET Friday | Use weekly template; load temporal briefs first; write weekly rollup and deploy/index artifacts. |

Cron prompts are intentionally self-contained and reference the docs above so scheduled runs do not fall back to stale prompt formats.

## Fresh-run verification checklist

Before reporting success for any run:

- `python3.12 -m py_compile scripts/*.py` for changed scripts.
- `search_plan.json` contains `schema_version`, `briefing_template`, `topic_keyword_pack`, `lanes`, `agent_execution`, `verification_gates`, and `handoff_prompt_template`.
- `briefing.md` exists and follows the required section order for the mode.
- `dashboard.html` contains the Table of Contents and synthesized briefing markers.
- `archive.html` links only to files that exist on `gh-pages`.
- `data/index.json` and `data/index.html` include current project/run files.
- Live GitHub Pages cache-busted checks pass for:
  - `/index.html?v=<cachebuster>`
  - `/archive.html?v=<cachebuster>`
  - `/docs/index.html?v=<cachebuster>`
  - `/data/index.html?v=<cachebuster>`
- Live link check returns 0 missing links.

## Source and quality rules

- Prefer primary/official sources for market data, central banks, regulators, company releases, and filings.
- Use newswires and financial media for event discovery and market color.
- Full extraction is mandatory for narrative claims.
- Headline-only output is a failure.
- Stale article backfill is a failure.
- Unsupported numeric claims are a failure.
- If source quality is weak or conflicting, label it in `Source Notes and Data Quality`.

## Filesystem layout

```text
runs/{date}/{mode}/
├── search_plan.json       # mode/date/weekday-specific plan with agent lanes
├── articles.json          # accepted article records
├── articles_enriched.json # optional full extracted records
├── briefing.md            # authoritative research note
├── summary.md             # article/link digest only
└── dashboard.html         # rendered static dashboard

data/
├── sources.json
└── universe.json

docs/
├── briefing-template-spec.md
├── multi-agent-news-flow.md
├── daily-cycle-spec.md
├── archive.md
└── index.md
```

## Local commands

```bash
# Generate a plan only
python3.12 scripts/fetch_articles.py --mode pre-market --date YYYY-MM-DD --universe data/universe.json --sources data/sources.json --output /tmp/search_plan.json --plan-only

# Build dashboard from authoritative briefing
python3.12 scripts/build_dashboard.py --input runs/YYYY-MM-DD/MODE/articles.json --summary runs/YYYY-MM-DD/MODE/briefing.md --output runs/YYYY-MM-DD/MODE/dashboard.html --mode MODE --date YYYY-MM-DD

# Deploy and propagate docs/data indexes
python3.12 scripts/deploy.py --run-dir runs/YYYY-MM-DD/MODE --mode MODE --date YYYY-MM-DD
```
