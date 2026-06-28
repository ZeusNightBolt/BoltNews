# BoltNews Briefing Template Specification

BoltNews briefings are research notes, not headline digests. The authoritative artifact is `briefing.md`; `summary.md` is only an article/link digest and fallback input.

## Global contract

- Every briefing uses stable markdown headings so the dashboard can create an in-page table of contents.
- Every market claim with a price, yield, spread, percentage, index level, EPS, revenue, guidance item, timestamp, or policy probability must cite a source and as-of time/date.
- Current-news sections use fresh articles inside the run's recency window. Historical context must come from prior BoltNews markdown artifacts and be labeled as context.
- If a required section lacks verified data, keep the heading and write `Data unavailable — <reason>` rather than fabricating.
- Failure modes: headline-only output, missing current-market snapshot, stale article backfill, unsupported numeric claims, missing timestamps, section order drift, or Telegram delivery without a compact `## Senior PM Recap` sourced from the validated `briefing.md`.
- After validation/deploy, generate `senior_pm_recap.md` with `scripts/senior_pm_recap.py` and include it in the Telegram notification before links/log details. The recap must be compact, portfolio-manager style, and must not introduce claims absent from `briefing.md`.

## Pre-market template

Purpose: answer "Where are markets now, what happened overnight, and what is today's setup?"

Required section order:

1. `## Futures and Current Market Snapshot`
   - S&P 500 futures, Nasdaq futures, Dow futures, Russell 2000 futures if available.
   - VIX/VIX futures, 2Y/10Y/30Y Treasury yields, DXY, WTI/Brent, gold, BTC/ETH if material.
   - Required fields: level, change, percent/bp change, as-of time, source.

2. `## Overnight Top Developments`
   - 3–7 ranked developments since the prior U.S. close.
   - Required fields: event, source, timestamp, affected assets/tickers, numeric impact, why it matters today.

3. `## Global Session Recap`
   - Asia and Europe index performance, regional catalysts, cross-read to U.S. risk assets.

4. `## Macro, Rates, and Policy Setup`
   - Yield curve, Fed probabilities, today's economic calendar with release time / consensus / prior, central-bank or fiscal developments.

5. `## FX and Commodities`
   - DXY, EUR/USD, USD/JPY, GBP/USD if relevant, WTI, Brent, gold, copper if relevant, catalyst and cross-asset implication.

6. `## Equities and Single-Stock Watchlist`
   - Pre-market movers, earnings reactions, analyst actions, guidance, revenue/EPS/margins/backlog/capex where relevant.

7. `## Sector and Factor Setup`
   - Expected leadership/laggards, growth/value, small/large, cyclicals/defensives, breadth and positioning.

8. `## Today's Risk Map`
   - Scheduled catalysts with times, unscheduled risks, key levels, bull/base/bear scenarios.

9. `## Source Notes and Data Quality`
   - Sources grouped by market data, macro/policy, companies, news; disclose stale/conflicting/unavailable data.

## Post-market template

Purpose: answer "What moved today, what changed, and what carries into tomorrow?"

Required section order:

1. `## Closing Market Snapshot`
   - S&P 500, Nasdaq, Dow, Russell 2000 closes; VIX; 2Y/10Y/30Y; DXY; WTI/Brent/gold; BTC/ETH if material; breadth if available.

2. `## Why Markets Moved`
   - 3–5 primary drivers ranked by importance with catalyst, asset-class response, numeric move, timestamp/source, persistence assessment.

3. `## Equity Market Internals`
   - Sector performance, breadth, factors, mega-cap contribution, technical levels.

4. `## Rates, Macro, and Policy`
   - Macro prints with actual/consensus/prior, curve move, Fed/central-bank commentary, implied policy probabilities.

5. `## Earnings and Corporate Developments`
   - During-session and after-hours earnings with EPS, revenue, guidance, margin/backlog/capex/buyback details, stock reaction, source.

6. `## Cross-Asset Confirmation or Divergence`
   - Equities vs rates vs FX vs commodities vs vol; identify confirmations, contradictions, and potential mispricing.

7. `## Tomorrow Setup`
   - Overnight earnings/events, next-day macro calendar, key levels, watchlist.

8. `## Source Notes and Data Quality`

## Weekend template

Purpose: answer "What changed this week, what matters next week, and what risks are underpriced?"

Required section order:

1. `## Weekly Market Scoreboard`
   - Weekly and Friday-close levels for major indices, VIX, 2Y/10Y/30Y, DXY, WTI/Brent/gold, crypto if material.

2. `## The Week's Core Narrative`
   - 3–5 themes, evidence across assets, what changed from prior week, what is unresolved.

3. `## Macro and Policy Review`
   - Major data releases with actual/consensus/prior, Fed/central-bank developments, curve interpretation, next-week macro calendar.

4. `## Equity and Sector Review`
   - Sector winners/losers, factors, single-stock/earnings moves, valuation/positioning context.

5. `## Commodities, FX, Credit, and Volatility`
   - Weekly moves, cross-asset divergences, risk/stress signals.

6. `## Geopolitics and Event Risk`
   - Material developments, transmission channel, weekend gap risk, source/timestamp.

7. `## Next Week Playbook`
   - Day-by-day macro/events/earnings calendar, levels to watch, bull/base/bear scenarios.

8. `## Historical Context`
   - Clearly labeled older-than-48h context from BoltNews archives only.

9. `## Source Notes and Data Quality`

## Weekly rollup template

Source priority: `daily/temporal_brief.md` → each run's `briefing.md` → `summary.md` only as fallback.

Required section order:

1. `## Weekly Executive Summary`
2. `## Cross-Run Data Evolution`
   - Old value, new value, change, source, timestamp; confirmed/evolved/stale/contradicted flags.
3. `## Asset-Class Weekly Review`
   - Equities, Rates, Credit, FX, Commodities, Volatility, Crypto if relevant.
4. `## Theme Tracker`
   - Persistent, new, faded, contradicted themes.
5. `## Calendar and Risk Preview`
6. `## Data Quality Appendix`

Weekly rollup failure: concatenating daily notes without comparing data-point evolution.
