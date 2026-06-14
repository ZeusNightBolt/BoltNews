---
title: Fix Link-Only GitHub Pages Dashboard — 2026-06-08
type: solution
project: boltnews
created: 2026-06-08T08:35:55.969959
tags: [boltnews, github-pages, dashboard, cron, briefing]
related_tasks: []
---

# Fix Link-Only GitHub Pages Dashboard — 2026-06-08

## Problem

<!-- What was the problem? -->

## Solution

Investigated why BoltNews GitHub Pages showed only links while Telegram had a full synthesized briefing.

Root cause:
- The scheduled agent produced the research note in its final Telegram response after the deterministic pipeline had already built and deployed GitHub Pages.
- The deployed dashboard used runs/YYYY-MM-DD/mode/summary.md.
- In BoltNews, summary.md is currently an article/category digest with source links, not the final synthesized briefing.
- Therefore Telegram showed the agent's final synthesized response, while GitHub Pages showed the earlier deterministic link digest.

Fixes applied:
- Extracted the 2026-06-08 pre-market synthesized briefing from cron output into runs/2026-06-08/pre-market/briefing.md.
- Modified scripts/build_dashboard.py to prefer briefing.md when present and refuse link-only markdown that lacks synthesized briefing markers such as Executive Summary or Cross-Asset.
- Modified scripts/deploy.py to refuse dashboards that do not contain synthesized briefing markers.
- Rebuilt runs/2026-06-08/pre-market/dashboard.html from briefing.md.
- Redeployed GitHub Pages.
- Updated BoltNews pre-market and post-market cron prompts so future runs write briefing.md before rebuild/deploy and verify deployed dashboard content.
- Updated the boltnews-pipeline skill to encode this failure mode and required dashboard content source.
- Pushed repo fix via PR #1 in ZeusNightBolt/BoltNews and merged it.

Verification:
- Reproduced the live link-only page in browser.
- Regression test: a link-only summary now causes build_dashboard.py to exit nonzero.
- Rebuilt current dashboard from briefing.md; output contained Executive Summary and source links section.
- Deployed to GitHub Pages.
- Raw GitHub Pages index contained Executive Summary and unique briefing text.
- Live GitHub Pages updated after CDN delay and browser showed Executive Summary, Asset Class Deep Dive tables, and no JS console errors/messages.

Key paths:
- Cron output: /home/nima/.hermes/cron/output/57148987bc98/2026-06-08_06-10-09.md
- Fixed briefing: /home/nima/.hermes/os/projects/boltnews/runs/2026-06-08/pre-market/briefing.md
- Fixed dashboard: /home/nima/.hermes/os/projects/boltnews/runs/2026-06-08/pre-market/dashboard.html
- Local repo checkout: /home/nima/repos/BoltNews
- GitHub PR: https://github.com/ZeusNightBolt/BoltNews/pull/1

## Key Details

<!-- Specific implementation details, config values, patterns used -->

## Files

- `/home/nima/.hermes/os/projects/boltnews/scripts/build_dashboard.py`
- `/home/nima/.hermes/os/projects/boltnews/scripts/deploy.py`
- `/home/nima/.hermes/os/projects/boltnews/runs/2026-06-08/pre-market/briefing.md`

## Gotchas

<!-- What tripped you up? What would you do differently? -->
