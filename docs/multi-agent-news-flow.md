# BoltNews Multi-Agent Discovery and Synthesis Flow

This document formalizes the agent handoff and timeout structure used to populate `articles.json` and produce a section-complete `briefing.md` without overloading one reasoning window.

## Design goal

Split discovery into bounded lanes. Each lane receives a self-contained prompt with mode, date, recency window, assigned topics, source rules, and output schema. The orchestrator only aggregates lane outputs and runs verification gates.

## Plan generation

`scripts/fetch_articles.py --plan-only` writes `search_plan.json` with:

- `schema_version`
- `recency` window and timestamp policy
- `briefing_template` section order
- `topic_keyword_pack` for weekday + mode
- `agent_execution` global timeouts / retry policy
- `lanes` with per-lane search/extract budgets
- `verification_gates`
- `handoff_prompt_template`

## Agent lanes

Default lanes:

1. `market-snapshot`
   - Futures/closing market data, yields, DXY, oil, gold, vol, crypto.
   - Must anchor the first section of every briefing.

2. `overnight-or-session-headlines`
   - Overnight developments for pre-market, session drivers for post-market, week narrative for weekend.

3. `macro-policy-rates-fx`
   - Fed, central banks, inflation, jobs, Treasury curve, dollar and major FX.

4. `equities-earnings-single-stocks`
   - Earnings, guidance, analyst actions, sector leaders/laggards, pre/after-market movers.

5. `commodities-credit-vol`
   - Oil/gas/metals, credit spreads/defaults/refinancing, VIX/options/volatility.

6. `dedupe-validation-synthesis`
   - Merges lane JSON, rejects stale/no-timestamp/headline-only records, and checks coverage before `briefing.md` is written.

## Timeout defaults

- Global discovery budget: 1,800 seconds.
- Lane timeout: 300–480 seconds depending lane.
- Search timeout: 45 seconds per query.
- Extraction timeout: 75 seconds per URL.
- Retries: 2 per query, SearXNG backoff `[3, 8, 20]` seconds.
- If a lane times out, preserve partial results and mark status `partial`; do not backfill with stale articles.

## Required subagent handoff context

Every lane prompt must include:

```text
You are a BoltNews article discovery subagent.
Mode: {mode}
Target date: {target_date}
Weekday: {weekday}
Recency window: {window_start_iso} to {window_end_iso}
Timezone: America/New_York
Lane: {lane}
Assigned section(s): {sections}
Assigned search items: {items}
Query templates: {query_templates}
Timeouts: search={search_timeout_seconds}s, extraction={extract_timeout_seconds}s, lane={lane_timeout_seconds}s

Rules:
1. Accept only articles published inside the recency window.
2. Every accepted article requires headline/title, url, canonical_url if available, source, published_at, fetched_at, tickers/topics, assigned_section, summary/lead paragraph, extracted_text or substantive body excerpt.
3. Reject missing publication timestamps unless an official live market quote page is explicitly used for the market snapshot; label it as market_data, not article.
4. Reject stale articles, evergreen pages, quote pages masquerading as news, and old analysis.
5. Do not web-search historical context. Use prior BoltNews markdown artifacts only.
6. Prefer Reuters/Bloomberg/WSJ/CNBC/MarketWatch/Yahoo/official releases/central banks/exchanges/regulators.
7. Full extraction is required for narrative claims. Headline-only records are failures.
8. Return JSON only.
```

## Lane output schema

```json
{
  "lane": "macro-policy-rates-fx",
  "started_at": "ISO",
  "finished_at": "ISO",
  "status": "ok|partial|failed",
  "stats": {
    "queries_attempted": 0,
    "queries_timed_out": 0,
    "rate_limits": 0,
    "articles_found": 0,
    "articles_accepted": 0,
    "articles_rejected_stale": 0,
    "articles_rejected_no_timestamp": 0
  },
  "articles": [
    {
      "title": "",
      "headline": "",
      "url": "",
      "canonical_url": "",
      "source": "",
      "source_class": "",
      "published_at": "",
      "fetched_at": "",
      "author": "",
      "tickers": [],
      "topics": [],
      "assigned_section": "Macro, Rates, and Policy Setup",
      "summary": "",
      "lead_paragraph": "",
      "extracted_text": "",
      "discovered_by_query": "",
      "lane": "macro-policy-rates-fx",
      "freshness_verified": true
    }
  ],
  "errors": []
}
```

## Verification gates before `articles.json`

1. Schema gate: required keys present.
2. Timestamp gate: every article has parseable `published_at` inside the recency window, except explicitly labeled live market data.
3. Freshness gate: stale indicators rejected unless clearly historical context.
4. Extraction gate: reject headline-only records; require substantive body or lead paragraph.
5. Relevance gate: market signal keywords or direct macro/asset relevance required.
6. Deduplication gate: canonical URL, normalized URL, headline/source pair.
7. Coverage gate: market snapshot + top developments + at least four asset-class lanes represented.
8. Briefing gate: rendered `briefing.md` contains all required sections for the run mode.
9. Dashboard gate: generated page has heading-derived TOC anchors and no missing internal links.

## Context-budget discipline

- The orchestrator never ingests full extracted text from all lanes unless synthesis requires it.
- Lane agents return compact JSON plus extracted snippets.
- If context grows too large, write lane outputs to disk and hand off via goal mode: the next agent receives file paths, schema, acceptance criteria, and no raw transcript dump.
