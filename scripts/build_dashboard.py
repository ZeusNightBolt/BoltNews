#!/usr/bin/env python3.12
"""
BoltNews — Dashboard Builder.
Builds a self-contained GitHub-dark-style HTML dashboard with all articles.
Categorized, searchable, mobile-responsive.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>BoltNews — {mode_label} | {date}</title>
<style>
  :root {{
    --bg: #0d1117;
    --bg-secondary: #161b22;
    --bg-tertiary: #21262d;
    --border: #30363d;
    --text: #c9d1d9;
    --text-muted: #8b949e;
    --accent: #58a6ff;
    --accent-emphasis: #1f6feb;
    --green: #3fb950;
    --red: #f85149;
    --amber: #d29922;
    --purple: #a371f7;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    min-height: 100dvh;
  }}
  .container {{ max-width: 900px; margin: 0 auto; padding: 16px; }}
  
  /* Header */
  .header {{
    border-bottom: 1px solid var(--border);
    padding: 24px 0 16px 0;
    margin-bottom: 24px;
  }}
  .header h1 {{ font-size: 1.5rem; font-weight: 600; color: var(--text); }}
  .header .subtitle {{ font-size: 0.85rem; color: var(--text-muted); margin-top: 4px; }}
  .header .badge {{
    display: inline-block;
    background: var(--accent-emphasis);
    color: #fff;
    font-size: 0.75rem;
    padding: 2px 8px;
    border-radius: 12px;
    margin-left: 8px;
    vertical-align: middle;
  }}
  
  /* Search */
  .search-bar {{
    width: 100%;
    padding: 10px 16px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-size: 0.9rem;
    margin-bottom: 24px;
    outline: none;
    transition: border-color 0.2s;
  }}
  .search-bar:focus {{ border-color: var(--accent); }}
  .search-bar::placeholder {{ color: var(--text-muted); }}
  
  /* Category tabs */
  .tabs {{
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
    margin-bottom: 24px;
    border-bottom: 2px solid var(--border);
    padding-bottom: 8px;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }}
  .tab {{
    padding: 6px 14px;
    background: transparent;
    border: none;
    color: var(--text-muted);
    font-size: 0.85rem;
    cursor: pointer;
    border-radius: 6px 6px 0 0;
    white-space: nowrap;
    touch-action: manipulation;
    min-height: 36px;
    font-family: inherit;
    transition: color 0.15s, background 0.15s;
  }}
  .tab:hover {{ color: var(--text); background: var(--bg-tertiary); }}
  .tab.active {{ color: var(--text); border-bottom: 2px solid var(--accent); margin-bottom: -10px; font-weight: 600; }}
  .tab .count {{ font-size: 0.7rem; color: var(--text-muted); margin-left: 4px; }}
  
  /* Article cards */
  .article-list {{ display: flex; flex-direction: column; gap: 8px; }}
  .article-card {{
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px 16px;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
    text-decoration: none;
    color: inherit;
    display: block;
  }}
  .article-card:hover {{ border-color: var(--accent); background: var(--bg-tertiary); }}
  .article-card .ticker-tag {{
    display: inline-block;
    background: var(--bg);
    border: 1px solid var(--border);
    color: var(--accent);
    font-size: 0.7rem;
    font-weight: 600;
    padding: 1px 6px;
    border-radius: 4px;
    margin-right: 8px;
    font-family: "SF Mono", Consolas, monospace;
    vertical-align: middle;
  }}
  .article-card .title {{
    font-size: 0.95rem;
    font-weight: 600;
    margin-bottom: 4px;
    display: inline;
  }}
  .article-card .meta {{
    font-size: 0.75rem;
    color: var(--text-muted);
    margin-top: 6px;
  }}
  .article-card .description {{
    font-size: 0.82rem;
    color: var(--text-muted);
    margin-top: 6px;
    line-height: 1.5;
  }}
  
  /* Empty state */
  .empty-state {{
    text-align: center;
    padding: 60px 20px;
    color: var(--text-muted);
  }}
  .empty-state h3 {{ font-size: 1.1rem; margin-bottom: 8px; }}
  
  /* Footer */
  .footer {{
    text-align: center;
    padding: 32px 0;
    color: var(--text-muted);
    font-size: 0.75rem;
    border-top: 1px solid var(--border);
    margin-top: 40px;
  }}
  
  /* Category colors */
  .cat-Rates {{ border-left: 3px solid var(--amber); }}
  .cat-FX {{ border-left: 3px solid var(--purple); }}
  .cat-Credit {{ border-left: 3px solid var(--red); }}
  .cat-Equities {{ border-left: 3px solid var(--green); }}
  .cat-Derivatives {{ border-left: 3px solid #79c0ff; }}
  .cat-Macro {{ border-left: 3px solid var(--accent); }}
  .cat-Regulatory {{ border-left: 3px solid #f0883e; }}
  
  /* Mobile */
  @media (max-width: 600px) {{
    .container {{ padding: 12px; }}
    .header h1 {{ font-size: 1.2rem; }}
    .article-card {{ padding: 12px; }}
    .tabs {{ gap: 0; }}
    .tab {{ padding: 6px 10px; font-size: 0.78rem; }}
  }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>⚡ BoltNews <span class="badge">{mode_label}</span></h1>
    <div class="subtitle">{date} &middot; {article_count} articles &middot; {category_count} categories</div>
  </div>
  
  <input type="text" class="search-bar" id="search" placeholder="Search articles..." oninput="filterArticles()">
  
  <div class="tabs" id="tabs">
    <button class="tab active" onclick="filterCategory('all')">All <span class="count">({article_count})</span></button>
    {tab_buttons}
  </div>
  
  <div class="article-list" id="article-list">
    {article_cards}
  </div>
  
  <div class="footer">
    BoltNews &copy; {year} &middot; Auto-generated {date} &middot; <a href="https://github.com/ZeusNightBolt/BoltNews" style="color: var(--accent)">GitHub</a>
  </div>
</div>

<script>
  function filterCategory(cat) {{
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    event.target.classList.add('active');
    document.querySelectorAll('.article-card').forEach(card => {{
      if (cat === 'all' || card.dataset.category === cat) {{
        card.style.display = '';
      }} else {{
        card.style.display = 'none';
      }}
    }});
  }}
  
  function filterArticles() {{
    const query = document.getElementById('search').value.toLowerCase();
    document.querySelectorAll('.article-card').forEach(card => {{
      const text = (card.dataset.search || '').toLowerCase();
      card.style.display = text.includes(query) ? '' : 'none';
    }});
  }}
</script>
</body>
</html>"""


def build_dashboard(articles: list[dict], mode: str, run_date: str) -> str:
    """Build the HTML dashboard."""
    if mode == "weekend":
        mode_label = "Weekend Briefing"
    elif mode == "pre-market":
        mode_label = "Pre-Market"
    else:
        mode_label = "Post-Market"
    
    from collections import defaultdict, Counter
    by_category = defaultdict(list)
    for a in articles:
        cat = a.get("category", "Equities")
        by_category[cat].append(a)
    
    sorted_cats = sorted(by_category.items(), key=lambda x: len(x[1]), reverse=True)
    
    # Tab buttons
    tab_buttons = "\n    ".join(
        f'<button class="tab" onclick="filterCategory(\'{cat}\')">{cat} <span class="count">({len(arts)})</span></button>'
        for cat, arts in sorted_cats
    )
    
    # Article cards
    cards = []
    for cat, cat_articles in sorted_cats:
        for a in cat_articles:
            ticker_tag = f'<span class="ticker-tag">{a["ticker"]}</span>' if a.get("ticker") else ""
            title = a.get("title", "Untitled")
            summary = a.get("summary", "")
            desc = a.get("description", "")
            url = a.get("url", "#")
            source = a.get("source", "unknown")
            
            search_text = f"{a.get('ticker', '')} {title} {desc}".lower()
            
            card = f"""<a class="article-card cat-{cat}" href="{url}" target="_blank" rel="noopener" 
                 data-category="{cat}" data-search="{search_text}">
      {ticker_tag}<span class="title">{title}</span>
      <div class="description">{summary or desc[:300]}</div>
      <div class="meta">{source} &middot; {cat}</div>
    </a>"""
            cards.append(card)
    
    article_cards = "\n    ".join(cards) if cards else """<div class="empty-state">
      <h3>No Articles Found</h3>
      <p>This session did not find any market-moving news.</p>
    </div>"""
    
    # Category count: unique categories
    category_count = len(sorted_cats)
    
    html = DASHBOARD_TEMPLATE.format(
        mode_label=mode_label,
        date=run_date,
        article_count=len(articles),
        category_count=category_count,
        tab_buttons=tab_buttons,
        article_cards=article_cards,
        year=run_date[:4],
    )
    
    return html


def main():
    parser = argparse.ArgumentParser(description="BoltNews Dashboard Builder")
    parser.add_argument("--input", type=Path, required=True, help="articles.json or enriched JSON")
    parser.add_argument("--summary", type=Path, required=True, help="summary.md (for reference)")
    parser.add_argument("--output", type=Path, required=True, help="dashboard.html output")
    parser.add_argument("--mode", choices=["pre-market", "post-market", "weekend"], required=True)
    parser.add_argument("--date", type=str, required=True)
    args = parser.parse_args()
    
    # Load articles (try enriched first)
    enriched_path = args.input.parent / "articles_enriched.json"
    articles_path = enriched_path if enriched_path.exists() else args.input
    
    with open(articles_path) as f:
        data = json.load(f)
    
    # Handle both raw articles list and wrapped format
    if isinstance(data, list):
        articles = data
    elif isinstance(data, dict):
        articles = data.get("articles", [])
        # Try enriched format (direct list of articles with categories)
        if not articles and isinstance(data, list):
            articles = data
        elif not articles:
            # It might be the enriched format directly
            articles = [data] if data.get("title") else []
    
    html = build_dashboard(articles, args.mode, args.date)
    
    with open(args.output, "w") as f:
        f.write(html)
    
    print(f"Dashboard: {args.output} ({len(html)} bytes, {len(articles)} articles)")


if __name__ == "__main__":
    main()
