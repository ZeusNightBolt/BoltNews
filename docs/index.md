# BoltNews Docs Index

Live dashboard: https://zeusnightbolt.github.io/BoltNews/

Archive: https://zeusnightbolt.github.io/BoltNews/archive.html

Data index: https://zeusnightbolt.github.io/BoltNews/data/index.html

## Current operating contract

BoltNews is a cross-asset research briefing pipeline, not a headline aggregator. The authoritative content artifact is:

```text
runs/{YYYY-MM-DD}/{mode}/briefing.md
```

`summary.md` is only an article/link digest and fallback input. Dashboards, Telegram delivery, archive pages, and weekly rollups should use `briefing.md` as the primary research note.

## Required briefing templates

- [Briefing Template Specification](briefing-template-spec.md)
  - Pre-market starts with `Futures and Current Market Snapshot`, then overnight headlines and the day setup.
  - Post-market starts with `Closing Market Snapshot`, then why markets moved and tomorrow's setup.
  - Weekend starts with `Weekly Market Scoreboard`, then cross-asset narrative and next-week risks.
  - Every mode ends with `Source Notes and Data Quality`.

- [Multi-Agent Discovery Flow](multi-agent-news-flow.md)
  - Uses bounded lanes: market snapshot, headlines, macro/rates/FX, equities/earnings, commodities/credit/vol, dedupe-validation-synthesis.
  - Requires lane timeouts, search/extraction timeouts, recency windows, weekday topic keywords, and JSON output schema.
  - Prevents reasoning-window overload by splitting discovery and preserving partial lane outputs.

## Daily and weekly cycle

- [Daily Cycle Spec](daily-cycle-spec.md)
  - 6 PM post-market run covers the trading session.
  - 6 AM pre-market run covers overnight and the day setup.
  - Temporal reasoning compares the two and writes `runs/{date}/daily/temporal_brief.md`.

- Weekly rollup
  - Friday 8 PM ET.
  - Loads temporal briefs first, then individual run `briefing.md` files.
  - Avoids mechanical concatenation.

## GitHub Pages propagation

`deploy.py` now regenerates and propagates:

- homepage dashboard from `briefing.md`
- `archive.html` from actual `gh-pages` files
- `docs/*.md`
- `docs/index.html`
- `data/project/sources.json`
- `data/project/universe.json`
- `data/runs/{date}/{mode}/*`
- `data/index.json`
- `data/index.html`
- `.nojekyll` so GitHub Pages serves markdown/data files literally

After deploy, verify cache-busted live URLs:

- `https://zeusnightbolt.github.io/BoltNews/index.html?v=<cachebuster>`
- `https://zeusnightbolt.github.io/BoltNews/archive.html?v=<cachebuster>`
- `https://zeusnightbolt.github.io/BoltNews/docs/index.html?v=<cachebuster>`
- `https://zeusnightbolt.github.io/BoltNews/data/index.html?v=<cachebuster>`

## Current briefings and artifacts

- [Historical Briefings & Weekly Rollups](archive.md)
- [Data Index](../data/index.html)
- [Project Sources](../data/project/sources.json)
- [Project Universe](../data/project/universe.json)

## Failure modes to prevent

- Headline-only briefings.
- Dashboard built from `summary.md` instead of `briefing.md`.
- Missing first section: futures/current snapshot for pre-market, closing snapshot for post-market, weekly scoreboard for weekend.
- Stale search results accepted as fresh news.
- Articles without timestamps accepted without disclosure.
- Archive links pointing to files that do not exist.
- GitHub Pages raw files visible on GitHub but 404ing on `github.io` because `.nojekyll` is missing.
- Cron prompts using old summary/link-index format instead of the new template and docs.
