#!/usr/bin/env python3.12
"""
BoltNews — Dashboard Builder.
Converts summary.md (the synthesized briefing) to a self-contained HTML page.
GitHub-dark theme, mobile-responsive. Does NOT generate article cards — 
that's the old headline-only format. The briefing IS the content.
"""
import argparse
import html
import json
import re
import sys
from datetime import date
from pathlib import Path


def md_to_html(md: str) -> str:
    """Convert BoltNews markdown briefing to clean HTML."""
    lines = md.split('\n')
    html_lines = []
    heading_counts: dict[str, int] = {}
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Horizontal rule
        if line.strip() == '---':
            html_lines.append('<hr class="divider">')
            i += 1
            continue
        
        # Table: detect pipe-delimited rows
        if '|' in line and line.strip().startswith('|'):
            table_rows = []
            while i < len(lines) and '|' in lines[i]:
                table_rows.append(lines[i])
                i += 1
            html_lines.append(_build_table(table_rows))
            continue
        
        # H1, H2, H3
        if line.startswith('### '):
            title = line[4:].strip()
            html_lines.append(f'<h3 id="{_heading_id(title, heading_counts)}">{_inline_md(title)}</h3>')
        elif line.startswith('## '):
            title = line[3:].strip()
            html_lines.append(f'<h2 id="{_heading_id(title, heading_counts)}">{_inline_md(title)}</h2>')
        elif line.startswith('# '):
            title = line[2:].strip()
            html_lines.append(f'<h1 id="{_heading_id(title, heading_counts)}">{_inline_md(title)}</h1>')
        
        # Unordered list
        elif line.strip().startswith('- '):
            list_items = []
            while i < len(lines) and (lines[i].strip().startswith('- ') or lines[i].strip().startswith('  -')):
                item = lines[i].strip()
                if item.startswith('- '):
                    item = item[2:]
                elif item.startswith('  -'):
                    item = item[3:]
                list_items.append(f'<li>{_inline_md(item)}</li>')
                i += 1
            html_lines.append(f'<ul>{"".join(list_items)}</ul>')
            continue
        
        # Bold text (standalone, not part of a header/list)
        elif line.startswith('**') and line.endswith('**'):
            html_lines.append(f'<p class="bold-line"><strong>{_inline_md(line[2:-2])}</strong></p>')
        
        # Empty lines
        elif not line.strip():
            pass  # skip
        
        # Blockquote
        elif line.strip().startswith('> '):
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith('> '):
                quote_lines.append(lines[i].strip()[2:])
                i += 1
            html_lines.append(f'<blockquote>{"<br>".join(_inline_md(q) for q in quote_lines)}</blockquote>')
            continue
        
        else:
            # Regular paragraph
            html_lines.append(f'<p>{_inline_md(line)}</p>')
        
        i += 1
    
    return '\n'.join(html_lines)


def build_toc(md: str) -> str:
    """Build an in-page table of contents from briefing headings."""
    entries: list[tuple[int, str, str]] = []
    heading_counts: dict[str, int] = {}
    for line in md.split('\n'):
        if line.startswith('### '):
            level, title = 3, line[4:].strip()
        elif line.startswith('## '):
            level, title = 2, line[3:].strip()
        elif line.startswith('# '):
            level, title = 1, line[2:].strip()
        else:
            continue
        if not title:
            continue
        # Keep the body title addressable, but the TOC itself is for section navigation.
        if level == 1 and entries:
            continue
        entries.append((level, title, _heading_id(title, heading_counts)))

    section_entries = [(level, title, anchor) for level, title, anchor in entries if level >= 2]
    if not section_entries:
        return ''

    items = []
    for level, title, anchor in section_entries:
        items.append(
            f'<a class="toc-link toc-level-{level}" href="#{html.escape(anchor, quote=True)}">'
            f'{html.escape(_strip_inline_md(title))}</a>'
        )
    return (
        '<nav class="toc-card" aria-label="Briefing table of contents">'
        '<div class="toc-eyebrow">Briefing Navigation</div>'
        '<h2 class="toc-title">Table of Contents</h2>'
        f'<div class="toc-grid">{"".join(items)}</div>'
        '</nav>'
    )


def _strip_inline_md(text: str) -> str:
    """Strip simple inline markdown for plain-text labels and slugs."""
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1', text)
    text = re.sub(r'[`*_]+', '', text)
    return html.unescape(text).strip()


def _slugify(text: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', _strip_inline_md(text).lower()).strip('-')
    return slug or 'section'


def _heading_id(title: str, counts: dict[str, int]) -> str:
    base = _slugify(title)
    counts[base] = counts.get(base, 0) + 1
    if counts[base] == 1:
        return base
    return f'{base}-{counts[base]}'


def _build_table(rows: list[str]) -> str:
    """Build an HTML table from pipe-delimited rows."""
    if len(rows) < 2:
        return ''
    
    # Parse header and separator
    headers = [c.strip() for c in rows[0].split('|')[1:-1]]
    # Skip separator row (|---|---|)
    data_rows = rows[2:] if len(rows) > 2 else []
    
    html = '<div class="table-wrapper"><table>'
    html += '<thead><tr>' + ''.join(f'<th>{_inline_md(h)}</th>' for h in headers) + '</tr></thead>'
    html += '<tbody>'
    for row in data_rows:
        cells = [c.strip() for c in row.split('|')[1:-1]]
        html += '<tr>' + ''.join(f'<td>{_inline_md(c)}</td>' for c in cells) + '</tr>'
    html += '</tbody></table></div>'
    return html


def _inline_md(text: str) -> str:
    """Convert inline markdown safely: **bold**, *italic*, `code`, [links](url)."""
    placeholders: list[str] = []

    def stash(value: str) -> str:
        placeholders.append(value)
        return f"@@BNPH{len(placeholders)-1}@@"

    def link_repl(match: re.Match) -> str:
        label = html.escape(match.group(1), quote=False)
        url = html.escape(match.group(2), quote=True)
        if not (url.startswith("http://") or url.startswith("https://") or url.startswith("#")):
            url = "#"
        return stash(f'<a href="{url}" target="_blank" rel="noopener">{label}</a>')

    def code_repl(match: re.Match) -> str:
        code = html.escape(match.group(1), quote=False)
        cls = ' class="ticker"' if re.fullmatch(r"[A-Z]{2,5}", match.group(1)) else ""
        return stash(f"<code{cls}>{code}</code>")

    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', link_repl, text)
    text = re.sub(r'`([^`]+)`', code_repl, text)
    text = html.escape(text, quote=False)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<!\*)\*([^*]+?)\*(?!\*)', r'<em>\1</em>', text)
    for i, value in enumerate(placeholders):
        text = text.replace(f"@@BNPH{i}@@", value)
    return text


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
    line-height: 1.7;
    min-height: 100dvh;
    font-size: 15px;
  }}
  .container {{ max-width: 920px; margin: 0 auto; padding: 20px 24px; }}

  /* Navigation */
  .navbar {{
    position: sticky;
    top: 0;
    z-index: 10;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    margin: 0 0 22px 0;
    padding: 10px 0 12px 0;
    background: linear-gradient(180deg, rgba(13,17,23,0.98) 0%, rgba(13,17,23,0.90) 100%);
    backdrop-filter: blur(10px);
    border-bottom: 1px solid var(--border);
  }}
  .brand-mark {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: var(--text);
    font-weight: 700;
    letter-spacing: 0.2px;
    text-decoration: none;
  }}
  .nav-links {{ display: inline-flex; align-items: center; gap: 8px; }}
  .nav-item {{
    color: var(--text-muted);
    border: 1px solid transparent;
    border-radius: 999px;
    padding: 5px 12px;
    font-size: 0.82rem;
    text-decoration: none;
  }}
  .nav-item:hover {{
    color: var(--text);
    background: var(--bg-secondary);
    border-color: var(--border);
    text-decoration: none;
  }}
  .nav-item.active {{
    color: #fff;
    background: var(--accent-emphasis);
  }}

  /* Header */
  .header {{
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 22px 22px 18px 22px;
    margin-bottom: 30px;
    background:
      radial-gradient(circle at top left, rgba(88,166,255,0.14), transparent 34%),
      linear-gradient(180deg, rgba(22,27,34,0.95), rgba(13,17,23,0.95));
    box-shadow: 0 18px 48px rgba(1,4,9,0.28);
  }}
  .header h1 {{ font-size: 1.65rem; font-weight: 750; color: var(--text); letter-spacing: -0.02em; }}
  .header .badge {{
    display: inline-block;
    background: var(--accent-emphasis);
    color: #fff;
    font-size: 0.7rem;
    padding: 2px 10px;
    border-radius: 12px;
    margin-left: 10px;
    vertical-align: middle;
    font-weight: 500;
  }}
  .header .subtitle {{ font-size: 0.82rem; color: var(--text-muted); margin-top: 6px; }}

  /* Table of contents */
  .toc-card {{
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 18px;
    margin: 0 0 28px 0;
    background: linear-gradient(180deg, rgba(22,27,34,0.92), rgba(13,17,23,0.92));
  }}
  .toc-eyebrow {{
    color: var(--accent);
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-bottom: 4px;
  }}
  .toc-title {{
    border-bottom: none;
    margin: 0 0 12px 0;
    padding: 0;
    font-size: 1.05rem;
  }}
  .toc-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
    gap: 8px;
  }}
  .toc-link {{
    display: block;
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 8px 10px;
    background: var(--bg);
    color: var(--text);
    font-size: 0.86rem;
    text-decoration: none;
  }}
  .toc-link:hover {{
    border-color: var(--accent);
    color: #fff;
    text-decoration: none;
  }}
  .toc-level-3 {{
    color: var(--text-muted);
    padding-left: 18px;
    font-size: 0.82rem;
  }}

  h1, h2, h3 {{ scroll-margin-top: 78px; }}

  /* Content typography */
  h1 {{ font-size: 1.5rem; font-weight: 700; margin: 32px 0 12px 0; color: var(--text); }}
  h2 {{ font-size: 1.2rem; font-weight: 600; margin: 28px 0 10px 0; color: var(--text); border-bottom: 1px solid var(--border); padding-bottom: 6px; }}
  h3 {{ font-size: 1.05rem; font-weight: 600; margin: 20px 0 8px 0; color: var(--text); }}
  p {{ margin: 8px 0 12px 0; color: var(--text); }}
  p.bold-line {{ margin: 6px 0 6px 0; color: var(--text-muted); }}

  /* Links */
  a {{ color: var(--accent); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}

  /* Lists */
  ul {{ margin: 4px 0 16px 20px; }}
  li {{ margin: 3px 0; color: var(--text); }}

  /* Tables */
  .table-wrapper {{ overflow-x: auto; margin: 12px 0 20px 0; -webkit-overflow-scrolling: touch; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.88rem;
  }}
  th {{
    background: var(--bg-tertiary);
    color: var(--text-muted);
    font-weight: 600;
    text-align: left;
    padding: 8px 12px;
    border: 1px solid var(--border);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.3px;
  }}
  td {{
    padding: 7px 12px;
    border: 1px solid var(--border);
    color: var(--text);
  }}
  tr:nth-child(even) td {{ background: var(--bg-secondary); }}
  tr:hover td {{ background: rgba(88, 166, 255, 0.06); }}

  /* Blockquote */
  blockquote {{
    border-left: 3px solid var(--accent);
    margin: 12px 0;
    padding: 8px 16px;
    background: var(--bg-secondary);
    color: var(--text-muted);
    font-style: italic;
    border-radius: 0 6px 6px 0;
  }}

  /* Code */
  code {{
    background: var(--bg-tertiary);
    padding: 1px 5px;
    border-radius: 4px;
    font-family: "SF Mono", "Consolas", "Monaco", monospace;
    font-size: 0.85em;
    color: var(--accent);
  }}
  code.ticker {{
    background: var(--bg);
    border: 1px solid var(--border);
    color: var(--accent);
    font-weight: 600;
    padding: 1px 6px;
    font-size: 0.8em;
  }}

  /* Dividers */
  hr.divider {{
    border: none;
    border-top: 1px solid var(--border);
    margin: 24px 0;
  }}

  /* Footer */
  .footer {{
    text-align: center;
    padding: 36px 0;
    color: var(--text-muted);
    font-size: 0.75rem;
    border-top: 1px solid var(--border);
    margin-top: 48px;
  }}
  .footer a {{ color: var(--accent); }}

  /* Source reference section */
  .sources-section {{
    margin-top: 40px;
    padding-top: 24px;
    border-top: 2px solid var(--border);
  }}
  .sources-section h2 {{ border-bottom: none; font-size: 1rem; }}
  .source-link {{
    display: inline-block;
    margin: 3px 8px 3px 0;
    padding: 4px 10px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 4px;
    font-size: 0.78rem;
    color: var(--text-muted);
    text-decoration: none;
  }}
  .source-link:hover {{ border-color: var(--accent); color: var(--text); }}

  /* Mobile */
  @media (max-width: 600px) {{
    .container {{ padding: 12px 16px; }}
    .navbar {{ align-items: flex-start; flex-direction: column; gap: 8px; }}
    .nav-links {{ flex-wrap: wrap; }}
    .header {{ padding: 18px 16px 16px 16px; }}
    .header h1 {{ font-size: 1.3rem; }}
    h2 {{ font-size: 1.05rem; }}
    table {{ font-size: 0.78rem; }}
    th, td {{ padding: 5px 8px; }}
  }}
  @supports (-webkit-touch-callout: none) {{
    body {{ min-height: -webkit-fill-available; }}
  }}
</style>
</head>
<body>
<div class="container">
  <nav class="navbar" aria-label="BoltNews navigation">
    <a class="brand-mark" href="./index.html">⚡ BoltNews</a>
    <div class="nav-links">
      <a class="nav-item active" href="./index.html">Latest</a>
      <a class="nav-item" href="./archive.html">Archive</a>
      <a class="nav-item" href="https://github.com/ZeusNightBolt/BoltNews">GitHub</a>
    </div>
  </nav>
  <div class="header">
    <h1>⚡ BoltNews <span class="badge">{mode_label}</span></h1>
    <div class="subtitle">{date} &middot; {article_count} articles &middot; {category_count} categories</div>
  </div>

  {toc_html}

  <div class="content">
    {briefing_html}
  </div>

  {sources_html}

  <div class="footer">
    BoltNews &copy; {year} &middot; Generated {date} &middot; 
    <a href="https://github.com/ZeusNightBolt/BoltNews">GitHub</a>
  </div>
</div>
</body>
</html>"""


def build_dashboard(summary_md: str, articles: list[dict], mode: str, run_date: str) -> str:
    """Build the HTML dashboard from the synthesized briefing."""
    if mode == "weekend":
        mode_label = "Weekend Briefing"
    elif mode == "pre-market":
        mode_label = "Pre-Market"
    else:
        mode_label = "Post-Market"

    # Convert markdown briefing to HTML
    briefing_html = md_to_html(summary_md)
    toc_html = build_toc(summary_md)

    # Build source reference links from articles
    sources_lines = []
    article_count = len(articles)
    
    from collections import Counter
    cats = Counter(a.get("category", "Uncategorized") for a in articles)
    category_count = len(cats)

    if articles:
        sources_lines.append('<div class="sources-section">')
        sources_lines.append('<h2>📰 Source Articles</h2>')
        sources_lines.append('<p>')
        for a in articles:
            ticker = str(a.get("ticker", "")).strip()
            title = str(a.get("title", "Untitled"))[:80]
            url = str(a.get("url", "#"))
            if not (url.startswith("http://") or url.startswith("https://")):
                url = "#"
            label = f"{ticker}: {title}" if ticker else title
            sources_lines.append(
                f'<a class="source-link" href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">{html.escape(label)}</a>'
            )
        sources_lines.append('</p>')
        sources_lines.append('</div>')

    sources_html = '\n'.join(sources_lines)

    return DASHBOARD_TEMPLATE.format(
        mode_label=mode_label,
        date=run_date,
        article_count=article_count,
        category_count=category_count,
        toc_html=toc_html,
        briefing_html=briefing_html,
        sources_html=sources_html,
        year=run_date[:4],
    )


def main():
    parser = argparse.ArgumentParser(description="BoltNews Dashboard Builder")
    parser.add_argument("--input", type=Path, required=True, help="articles.json or enriched JSON")
    parser.add_argument("--summary", type=Path, required=True, help="summary.md (PRIMARY content source)")
    parser.add_argument("--output", type=Path, required=True, help="dashboard.html output")
    parser.add_argument("--mode", choices=["pre-market", "post-market", "weekend"], required=True)
    parser.add_argument("--date", type=str, required=True)
    args = parser.parse_args()

    # PRIMARY: Read synthesized briefing.md when present. summary.md is allowed
    # to be an article digest/link index, but the dashboard must render the
    # research briefing, not just source links.
    briefing_path = args.summary.parent / "briefing.md"
    content_path = briefing_path if briefing_path.exists() else args.summary
    if not content_path.exists():
        print(f"ERROR: briefing/summary markdown not found at {content_path}", file=sys.stderr)
        sys.exit(1)

    summary_md = content_path.read_text()
    synthesized_markers = ("Executive Summary", "Cross-Asset", "Weekly Market Scoreboard", "The Week's Core Narrative")
    if not any(marker in summary_md for marker in synthesized_markers):
        print(
            "ERROR: dashboard content is not a synthesized briefing "
            "(missing synthesized briefing markers). Refusing link-only dashboard.",
            file=sys.stderr,
        )
        sys.exit(2)

    # SECONDARY: Read articles.json for source links
    articles = []
    enriched_path = args.input.parent / "articles_enriched.json"
    # Avoid stale enriched feeds shadowing a freshly populated articles.json.
    # Prefer enriched only when it is at least as new as the input article feed.
    if enriched_path.exists() and enriched_path.stat().st_mtime >= args.input.stat().st_mtime:
        articles_path = enriched_path
    else:
        articles_path = args.input
    
    if not articles_path.exists():
        print(f"ERROR: article feed not found: {articles_path}", file=sys.stderr)
        sys.exit(3)
    try:
        with open(articles_path) as f:
            data = json.load(f)
        if isinstance(data, list):
            articles = data
        elif isinstance(data, dict):
            if {"search_queries", "prioritized_tickers", "recency_warning"} & set(data) and not data.get("articles"):
                print(f"ERROR: {articles_path} is a search plan, not an article feed", file=sys.stderr)
                sys.exit(3)
            articles = data.get("articles", data if data.get("title") else [])
        else:
            print(f"ERROR: unsupported article feed shape in {articles_path}", file=sys.stderr)
            sys.exit(3)
    except (json.JSONDecodeError, KeyError, OSError) as exc:
        print(f"ERROR: failed reading article feed {articles_path}: {exc}", file=sys.stderr)
        sys.exit(3)

    if not articles:
        print(f"ERROR: article feed has zero articles: {articles_path}", file=sys.stderr)
        sys.exit(3)

    # Build
    html = build_dashboard(summary_md, articles, args.mode, args.date)

    with open(args.output, "w") as f:
        f.write(html)

    print(f"Dashboard: {args.output} ({len(html)} bytes)")
    print(f"  Content source: {content_path}")
    print(f"  Summary: {len(summary_md)} chars → {len(md_to_html(summary_md))} chars HTML")
    print(f"  Source links: {len(articles)} articles")


if __name__ == "__main__":
    main()
