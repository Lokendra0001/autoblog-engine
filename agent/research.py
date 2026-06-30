"""Live web research for a chosen topic (Google News RSS), grounding the draft."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import quote

import requests

_UA = {"User-Agent": "Mozilla/5.0 (compatible; SEOContentAgent/1.0)"}


def research_topic(client, keyword: str) -> str:
    print(f"[RESEARCH] {keyword}")
    all_items = []
    queries = [keyword, f"{keyword} {client.geo_label}", f"{keyword} business"]
    geo = client.geo

    for query in queries:
        try:
            rss_url = (f"https://news.google.com/rss/search?q={quote(query)}"
                       f"&hl=en-{geo}&gl={geo}&ceid={geo}:en")
            resp = requests.get(rss_url, timeout=12, headers=_UA)
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item")[:5]:
                title = item.findtext("title", "").strip()
                desc = re.sub(r"<[^>]+>", "", item.findtext("description", "")).strip()[:160]
                pub = item.findtext("pubDate", "")[:16].strip()
                if title and title not in [x[0] for x in all_items]:
                    all_items.append((title, desc, pub))
        except Exception as e:
            print(f"[WARN] Research query failed ({query}): {e}")

    if not all_items:
        print("[WARN] No research data found.")
        return ""
    lines = [f"Research data for '{keyword}' (use as factual context, not direct quotes):"]
    for title, desc, pub in all_items[:8]:
        lines.append(f"• [{pub}] {title} — {desc}")
    print(f"[OK] Research: {len(all_items)} articles found.")
    return "\n".join(lines)
