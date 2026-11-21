"""Keyword research from Google search suggestions (what people actually type). Free, no key.

Used twice: when planning the month (pick keywords people really search for) and when
writing an article (the real questions behind a keyword, for the FAQ and section headings).
"""

from __future__ import annotations

import json
import time

import requests

_URL = "https://suggestqueries.google.com/complete/search"
_UA = {"User-Agent": "Mozilla/5.0 (compatible; AutoBlogEngine/1.0)"}
_PAUSE = 0.2  # seconds between requests: stay a polite, low-volume client

_SUFFIXES = ["", " vs", " price", " for", " in", " uses", " advantages", " disadvantages"]
_PREFIXES = ["is {}", "what is {}", "how {}", "why {}", "can {}"]


def suggest(query: str, client) -> list[str]:
    """Google's autocomplete suggestions for `query` in the client's country."""
    try:
        r = requests.get(_URL, headers=_UA, timeout=10,
                         params={"client": "firefox", "hl": "en", "gl": client.geo.lower(), "q": query})
        r.raise_for_status()
        return [s for s in json.loads(r.text)[1] if isinstance(s, str)]
    except Exception as e:
        print(f"[WARN] Search suggestions failed ({query}): {e}")
        return []
    finally:
        time.sleep(_PAUSE)


def _collect(queries, client, limit) -> list[str]:
    seen = {}
    for q in queries:
        for s in suggest(q, client):
            seen.setdefault(s.lower().strip(), None)
    return list(seen)[:limit]


def expand(seeds: list[str], client, limit=150) -> list[str]:
    """Real searches around the niche's seed terms (for monthly planning)."""
    queries = [s + suf for s in seeds for suf in _SUFFIXES] + [p.format(s) for s in seeds for p in _PREFIXES]
    return _collect(queries, client, limit)


def core_term(keyword: str, words=3) -> str:
    """The head of a long keyword ("rooftop solar subsidy for housing societies" -> "rooftop solar subsidy")."""
    return " ".join(keyword.lower().split()[:words])


def questions(keyword: str, client, limit=25) -> list[str]:
    """Real searches and questions around one article keyword (for FAQs and headings).
    Long keywords get few suggestions, so the core term is searched as well."""
    terms = list(dict.fromkeys([keyword.lower(), core_term(keyword)]))
    queries = [t for t in terms] + [p.format(t) for t in terms for p in _PREFIXES] + [f"{terms[-1]} vs"]
    return [s for s in _collect(queries, client, limit * 2) if s != keyword.lower()][:limit]
