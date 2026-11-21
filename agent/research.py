"""Research for one article keyword, from free sources that allow automated use:

- Google News RSS:   recent industry news (timeliness)
- OpenAlex:          recent research papers with abstracts (technical substance)
- Wikipedia:         neutral background on the core material/technology
- Google suggestions: the real searches and questions behind the keyword (FAQ, headings)

The result is a plain-text brief the writer and the editor both receive. The writer may use
facts from it; anything not in the brief or the company knowledge must stay qualitative.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date
from urllib.parse import quote

import requests

from . import keywords

_UA = {"User-Agent": "Mozilla/5.0 (compatible; AutoBlogEngine/1.0)"}
_TIMEOUT = 15


def news(client, keyword: str, limit=6) -> list[dict]:
    """Recent news headlines (last 12 months) about the keyword."""
    items, seen = [], set()
    for query in (keyword, f"{keyword} {client.geo_label}", keywords.core_term(keyword)):
        try:
            r = requests.get(f"https://news.google.com/rss/search?q={quote(query)}+when:1y"
                             f"&hl=en-{client.geo}&gl={client.geo}&ceid={client.geo}:en",
                             headers=_UA, timeout=_TIMEOUT)
            r.raise_for_status()
            for it in ET.fromstring(r.content).findall(".//item"):
                title = (it.findtext("title") or "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                items.append({"title": title, "source": (it.findtext("source") or "").strip(),
                              "date": (it.findtext("pubDate") or "")[5:16].strip()})
        except Exception as e:
            print(f"[WARN] News search failed ({query}): {e}")
        if len(items) >= limit:
            break
    return items[:limit]


def _abstract(inverted: dict | None) -> str:
    if not inverted:
        return ""
    pos = {p: w for w, ps in inverted.items() for p in ps}
    text = " ".join(pos[i] for i in sorted(pos))
    return re.sub(r"^(abstract[:.\s]*)", "", text, flags=re.I).strip()


def papers(keyword: str, limit=4, years=6) -> list[dict]:
    """Recent research papers (title, year, journal, abstract excerpt) from OpenAlex.
    Long keywords can be too specific, so the search is widened until something matches."""
    words = keyword.split()
    since = f"{date.today().year - years}-01-01"
    while words:
        try:
            r = requests.get("https://api.openalex.org/works", headers=_UA, timeout=_TIMEOUT, params={
                "search": " ".join(words),
                "filter": f"from_publication_date:{since},has_abstract:true,type:article",
                "sort": "relevance_score:desc", "per_page": limit,
                "select": "title,publication_year,abstract_inverted_index,primary_location"})
            r.raise_for_status()
            results = r.json().get("results", [])
        except Exception as e:
            print(f"[WARN] Research paper search failed: {e}")
            return []
        if len(results) >= 2 or len(words) <= 2:
            out = []
            for w in results:
                source = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
                abstract = _abstract(w.get("abstract_inverted_index"))
                if w.get("title") and abstract:
                    out.append({"title": w["title"], "year": w.get("publication_year"),
                                "journal": source, "abstract": abstract[:700]})
            return out
        words = words[:-1]
    return []


def background(keyword: str) -> dict | None:
    """Short Wikipedia summary of the most relevant article for the keyword's core term."""
    try:
        api = "https://en.wikipedia.org/w/api.php"
        s = requests.get(api, headers=_UA, timeout=_TIMEOUT, params={
            "action": "query", "list": "search", "srsearch": keywords.core_term(keyword, 2),
            "srlimit": 1, "format": "json"}).json()
        hits = s.get("query", {}).get("search", [])
        if not hits:
            return None
        title = hits[0]["title"]
        pages = requests.get(api, headers=_UA, timeout=_TIMEOUT, params={
            "action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1,
            "titles": title, "format": "json", "redirects": 1}).json()["query"]["pages"]
        extract = next(iter(pages.values())).get("extract", "").strip()
        return {"title": title, "text": extract[:1200]} if extract else None
    except Exception as e:
        print(f"[WARN] Background lookup failed: {e}")
        return None


def research_topic(client, keyword: str) -> str:
    print(f"[RESEARCH] {keyword}")
    found_news, found_papers = news(client, keyword), papers(keyword)
    bg, searches = background(keyword), keywords.questions(keyword, client)
    print(f"[OK] Research: {len(found_news)} news, {len(found_papers)} papers, "
          f"{'background, ' if bg else ''}{len(searches)} real searches")

    parts = [f"RESEARCH BRIEF for '{keyword}'. Use these facts accurately and in your own words; "
             "do not copy sentences. Refer to studies generally (e.g. \"a 2024 study on marine exposure\"), "
             "never invent authors, numbers or results beyond what is written here."]
    if searches:
        parts.append("REAL GOOGLE SEARCHES around this keyword (base the FAQ questions and some H2 headings "
                     "on the most relevant ones):\n" + "\n".join(f"- {s}" for s in searches))
    if found_papers:
        parts.append("RECENT RESEARCH PAPERS:\n" + "\n".join(
            f"- {p['title']} ({p['journal'] or 'journal'}, {p['year']}): {p['abstract']}" for p in found_papers))
    if found_news:
        parts.append("RECENT NEWS (last 12 months):\n" + "\n".join(
            f"- [{n['date']}] {n['title']}" for n in found_news))
    if bg:
        parts.append(f"BACKGROUND (Wikipedia, \"{bg['title']}\"):\n{bg['text']}")
    return "\n\n".join(parts) if len(parts) > 1 else ""
