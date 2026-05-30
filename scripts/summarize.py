#!/usr/bin/env python3.12
"""
BoltNews — Summarizer + Deduplicator.
- Clusters similar articles by content overlap
- Drops duplicates with same directional view
- Keeps contrasting views
- Generates categorized one-liner summaries
- Outputs markdown briefing
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

CATEGORIES = {
    "Rates": ["fed", "fomc", "interest rate", "treasury", "yield", "bond", "sofr", "libor",
              "central bank", "ecb", "boj", "boe", "monetary policy", "inflation", "cpi", "ppi"],
    "FX": ["forex", "currency", "dollar", "euro", "yen", "sterling", "yuan", "dxy", "usd",
           "fx", "exchange rate", "devaluation", "intervention"],
    "Credit": ["credit", "corporate bond", "high yield", "investment grade", "cds", "spread",
               "default", "distressed", "leveraged loan", "clo", "debt", "refinancing"],
    "Equities": ["stock", "equity", "share", "earnings", "revenue", "guidance", "dividend",
                 "buyback", "ipo", "index", "nasdaq", "dow", "s&p", "russell", "sector"],
    "Derivatives": ["option", "future", "derivative", "vix", "volatility", "hedge", "swap",
                    "gamma", "delta", "structured product", "etf", "etn"],
    "Macro": ["gdp", "payroll", "unemployment", "pmi", "ism", "consumer", "housing", "retail",
              "trade", "tariff", "geopolitical", "oil", "commodity", "energy", "recession"],
    "Regulatory": ["sec", "cftc", "doj", "antitrust", "regulation", "compliance", "fine",
                   "lawsuit", "litigation", "settlement", "probe", "investigation"],
}

BLOCKED_CATEGORIES = {
    "ESG/Social": ["esg", "climate", "carbon", "sustainability", "diversity", "inclusion",
                   "social", "activism", "protest", "gender", "racial", "equality"],
}


def load_articles(path: Path) -> list[dict]:
    with open(path) as f:
        data = json.load(f)
    return data.get("articles", [])


def categorize_article(article: dict) -> str:
    """Assign category based on title + description content."""
    text = (article.get("title", "") + " " + article.get("description", "")).lower()
    
    # First check blocked
    for cat, keywords in BLOCKED_CATEGORIES.items():
        if any(kw in text for kw in keywords):
            return None  # Blocked
    
    # Score categories
    scores = defaultdict(int)
    for cat, keywords in CATEGORIES.items():
        scores[cat] = sum(1 for kw in keywords if kw in text)
    
    if max(scores.values()) == 0:
        return "Equities"  # Default for ticker news
    
    return max(scores, key=scores.get)


def compute_similarity(a: dict, b: dict) -> float:
    """Simple Jaccard-like similarity on title + description word overlap."""
    def tokens(article):
        text = (article.get("title", "") + " " + article.get("description", "")).lower()
        return set(re.findall(r'\b[a-z]{4,}\b', text))
    
    ta = tokens(a)
    tb = tokens(b)
    if not ta or not tb:
        return 0.0
    
    intersection = ta & tb
    union = ta | tb
    return len(intersection) / len(union) if union else 0.0


def deduplicate(articles: list[dict], threshold: float = 0.35) -> list[dict]:
    """
    Cluster similar articles. Within each cluster:
    - If same directional view → keep only the most detailed one
    - If contrasting views → keep both
    """
    if not articles:
        return []
    
    kept = []
    clusters = []  # list of lists
    
    for article in articles:
        matched = False
        for cluster in clusters:
            # Check similarity with cluster representative
            if compute_similarity(article, cluster[0]) >= threshold:
                cluster.append(article)
                matched = True
                break
        if not matched:
            clusters.append([article])
    
    # Within each cluster, decide what to keep
    for cluster in clusters:
        if len(cluster) == 1:
            kept.append(cluster[0])
        else:
            # Check for contrasting views (simple heuristic: different sentiment implied)
            # Keep at most 2: the most detailed + one contrasting if found
            cluster.sort(key=lambda a: len(a.get("description", "")), reverse=True)
            kept.append(cluster[0])  # Most detailed
            
            # Check for contrasting view
            for other in cluster[1:]:
                desc_similarity = compute_similarity(cluster[0], other)
                if desc_similarity < 0.6 and desc_similarity >= threshold:
                    kept.append(other)
                    break
    
    return kept


def generate_one_liner(article: dict) -> str:
    """Generate a one-line summary from title + description."""
    title = article.get("title", "").strip()
    desc = article.get("description", "").strip()
    
    # Clean up title
    title = re.sub(r'\s+[-|]\s+.*$', '', title)  # Remove source suffix
    title = title.rstrip('.')
    
    if not desc:
        return title
    
    # Extract first sentence of description
    first_sent = re.split(r'[.!?]\s+', desc)[0].strip()
    if len(first_sent) < 30:
        first_sent = desc[:200].strip()
    
    # Combine
    if len(title) > 120:
        return title
    
    combined = f"{title} — {first_sent}"
    if len(combined) > 250:
        combined = combined[:247] + "..."
    
    return combined


def build_summary_markdown(articles: list[dict], mode: str, run_date: str) -> str:
    """Build the markdown briefing."""
    mode_label = "Pre-Market Briefing" if mode == "pre-market" else "Post-Market Recap"
    
    lines = [
        f"# BoltNews — {mode_label}",
        f"**{run_date}** | {len(articles)} articles",
        "",
    ]
    
    # Categorize
    by_category = defaultdict(list)
    for article in articles:
        cat = article.get("category", categorize_article(article))
        if cat is None:
            continue
        article["category"] = cat
        by_category[cat].append(article)
    
    # Sort categories by article count
    sorted_cats = sorted(by_category.items(), key=lambda x: len(x[1]), reverse=True)
    
    for cat, cat_articles in sorted_cats:
        lines.append(f"## {cat}")
        lines.append("")
        for a in cat_articles:
            ticker_tag = f"`{a['ticker']}` " if a.get("ticker") else ""
            one_liner = a.get("summary", generate_one_liner(a))
            url = a.get("url", "")
            source = a.get("source", "")
            
            if url:
                lines.append(f"- {ticker_tag}[{one_liner}]({url})")
            else:
                lines.append(f"- {ticker_tag}{one_liner}")
        lines.append("")
    
    # Stats
    lines.append("---")
    lines.append(f"*Generated by BoltNews • {len(articles)} articles • {len(sorted_cats)} categories*")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="BoltNews Summarizer")
    parser.add_argument("--input", type=Path, required=True, help="articles.json input")
    parser.add_argument("--output", type=Path, required=True, help="summary.md output")
    parser.add_argument("--mode", choices=["pre-market", "post-market"], required=True)
    parser.add_argument("--date", type=str, required=True)
    args = parser.parse_args()
    
    articles = load_articles(args.input)
    
    if not articles:
        print("WARNING: No articles to summarize. Writing empty summary.", file=sys.stderr)
        summary = f"# BoltNews — {'Pre-Market Briefing' if args.mode == 'pre-market' else 'Post-Market Recap'}\n\n**{args.date}** | 0 articles\n\n*No market-moving news found for this session.*\n"
    else:
        # Deduplicate
        original_count = len(articles)
        articles = deduplicate(articles)
        print(f"Deduplication: {original_count} → {len(articles)} articles")
        
        # Categorize and generate one-liners
        for a in articles:
            a["category"] = categorize_article(a)
            a["summary"] = generate_one_liner(a)
        
        # Filter out blocked categories
        articles = [a for a in articles if a["category"] is not None]
        print(f"After category filtering: {len(articles)} articles")
        
        summary = build_summary_markdown(articles, args.mode, args.date)
    
    with open(args.output, "w") as f:
        f.write(summary)
    
    # Also save enriched articles back
    enriched_path = args.input.parent / "articles_enriched.json"
    with open(enriched_path, "w") as f:
        json.dump(articles, f, indent=2, default=str)
    
    print(f"Summary: {args.output}")
    print(f"Enriched articles: {enriched_path}")


if __name__ == "__main__":
    main()
