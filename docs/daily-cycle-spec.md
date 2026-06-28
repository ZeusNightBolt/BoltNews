# BoltNews Daily Cycle — Specification

## Two-Run Architecture

BoltNews runs twice daily to capture the complete market news cycle:

```
6:00 AM ET  →  Pre-Market Run     →  runs/{today}/pre-market/
6:00 PM ET  →  Post-Market Run    →  runs/{today}/post-market/
```

After every 6 AM run completes, the **Temporal Reasoning Consolidator** combines:
- **Previous day's 6 PM** (post-market: full trading day coverage)
- **Today's 6 AM** (pre-market: overnight developments + day preview)

into a **Temporal Reasoning Brief** at `runs/{prev_date}/daily/` that shows HOW data points evolved between the two runs — not just a concatenation of two briefings.

## What Each Run Covers

### 6:00 AM — Pre-Market
| Aspect | Coverage |
|---|---|
| **Time window** | Previous day 4 PM → Today 6 AM (overnight) |
| **Content** | After-hours earnings, overnight macro, Asian/European session, pre-market futures, economic calendar preview |
| **Key question** | "What happened overnight and what's the setup for today?" |
| **Articles** | ~20-30, emphasis on breaking news and earnings releases |
| **Output** | `runs/{today}/pre-market/briefing.md` (authoritative), `senior_pm_recap.md` (Telegram lead), `summary.md` (link/article digest), `articles.json`, `dashboard.html` |

### 6:00 PM — Post-Market
| Aspect | Coverage |
|---|---|
| **Time window** | Today 9:30 AM → Today 4:00 PM (full trading session) |
| **Content** | Market close data, sector performance, earnings reports, economic data releases, Fed speeches, geopolitical developments, analyst actions |
| **Key question** | "What moved markets today and what's the positioning for tomorrow?" |
| **Articles** | ~10-20, emphasis on market-moving events and closing analysis |
| **Output** | `runs/{today}/post-market/briefing.md` (authoritative), `senior_pm_recap.md` (Telegram lead), `summary.md` (link/article digest), `articles.json`, `dashboard.html` |

## Temporal Reasoning Consolidation (CRITICAL)

After the 6 AM run, `scripts/reasoning_consolidate.py` produces:

```
runs/{prev_date}/daily/
├── temporal_brief.md        ← Temporal reasoning narrative (NOT concatenation)
├── temporal_diff.json       ← Machine-readable cross-run data point comparison
├── daily_context.md         ← Legacy combined markdown (from old consolidator)
└── context_dump.json        ← Legacy stats (from old consolidator)
```

### How Temporal Reasoning Works

The old `consolidate_daily.py` mechanically concatenated PM and AM summaries — it had ZERO awareness that data points change between 6PM and 6AM. Example: AVGO fell 12% after-hours at 6PM, but the AM run wrote about its pre-earnings $479 close as if nothing happened. The concatenated output stacked both narratives without reconciliation.

The new `reasoning_consolidate.py`:

1. **Extracts structured data points** from raw articles using regex patterns:
   - Price moves: after-hours prices, percent changes, stock prices
   - Earnings: revenue, EPS, guidance, AI revenue, FCF
   - Oil: WTI, Brent with % changes
   - Rates: 2Y, 10Y, 30Y, Fed funds with bp changes
   - Indices: S&P 500, Dow, Nasdaq, Russell 2000, VIX

2. **Groups data points by ticker + metric** and computes cross-run diffs:
   - **🔄 Evolved**: same metric appears in both runs with different values → shows direction + magnitude
   - **✅ Confirmed**: same value in both runs → data is stable
   - **⚠️ PM-only (stale risk)**: appears in PM but NOT in AM → may be outdated, needs verification
   - **🆕 AM-only (new)**: only in AM → overnight development PM didn't have

3. **Flags staleness explicitly**: "AVGO `after_hours_price: $421.86` — source: MarketBeat (6PM) — AM silent ⚠️"

4. **Attributes every data point** to its source and run time — no orphaned numbers

5. **Preserves 48-hour freshness rule**: articles >48h moved to Historical Context section

### Source Timestamp Requirement

Every article MUST carry a `fetched_at` or `published_at` timestamp. The PM and AM cron agents are instructed to include these. If missing, the consolidation engine falls back to `age_hours` from the article metadata. Articles without ANY timestamp are accepted but flagged with "age unknown."

### Why Temporal Reasoning Matters

- **No more stale data**: PM says AVGO -12% AH; AM doesn't mention it → flagged as stale risk, not silently ignored
- **Evolution tracking**: Oil went from $94.77 (6PM) to $95.31 (6AM) → direction + magnitude visible
- **Contradiction detection**: If PM says "earnings beat" and AM says "earnings miss" → flagged
- **Source attribution**: Every number has a source — no "market says" without a name and time

## Filesystem Layout

```
runs/
└── YYYY-MM-DD/
    ├── pre-market/           ← 6 AM run output
    │   ├── briefing.md       ← authoritative synthesized research note
    │   ├── senior_pm_recap.md← compact Telegram lead-in
    │   ├── summary.md        ← article/link digest
    │   ├── articles.json
    │   └── dashboard.html
    ├── post-market/          ← 6 PM run output
    │   ├── briefing.md       ← authoritative synthesized research note
    │   ├── senior_pm_recap.md← compact Telegram lead-in
    │   ├── summary.md        ← article/link digest
    │   ├── articles.json
    │   └── dashboard.html
    └── daily/                ← Temporal reasoning consolidation
        ├── temporal_brief.md       ← PRIMARY: cross-run evolution narrative
        ├── temporal_diff.json      ← Machine-readable diff data
        ├── daily_context.md        ← Legacy combined (for backward compatibility)
        └── context_dump.json       ← Legacy stats
```

## Cron Jobs

| Job | ID | Schedule | What It Does |
|---|---|---|---|
| Pre-Market | `57148987bc98` | 6:00 AM daily | Pipeline + temporal reasoning consolidation |
| Post-Market | `cffe38c452c9` | 6:00 PM daily | Pipeline only (no consolidation) |
| Weekly Rollup | `949d2440242b` | 8:00 PM Friday | Aggregate Mon-Fri temporal briefs |

## Verification

```bash
# Run temporal reasoning consolidator (dry run)
cd ~/.hermes/os/projects/boltnews
python3.12 scripts/reasoning_consolidate.py --dry-run

# Force specific date
python3.12 scripts/reasoning_consolidate.py --date 2026-06-03

# Check output
cat runs/2026-06-03/daily/temporal_brief.md

# Diff machine-readable output
cat runs/2026-06-03/daily/temporal_diff.json | python3.12 -m json.tool | head -30
```

## Design Principles

1. **Never concatenate when you can reason** — the old merge_summaries() just stacked text. The new engine compares data points.
2. **Timestamp everything** — every data point cites its source article and whether it came from the 6PM or 6AM run.
3. **Flag, don't hide** — stale data is explicitly marked as such, not silently carried forward.
4. **48-hour freshness** — articles >48h are pushed to Historical Context, not mixed with current news.
5. **Machine-readable alongside human-readable** — `temporal_diff.json` enables programmatic consumption.
