"""Topic discovery: Google Trends, Google News, AI-company RSS, YouTube creators.

Generalized from the NaviGo pipeline — feeds, geo and news query now come from
the client config so each tenant trends in its own niche.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests

from .ai import call_ai
from .state import ClientState

_UA = {"User-Agent": "Mozilla/5.0 (compatible; SEOContentAgent/1.0)"}


def fetch_rss_titles(url, label, limit=8, with_age=False):
    try:
        resp = requests.get(url, timeout=12, headers=_UA)
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.content)
        results = []
        now_utc = datetime.now(timezone.utc)
        ATOM = "{http://www.w3.org/2005/Atom}"
        items = root.findall(".//item")
        is_atom = False
        if not items:
            items = root.findall(f".//{ATOM}entry")
            is_atom = True
        for item in items[:limit]:
            title = (item.findtext(f"{ATOM}title", "") if is_atom else item.findtext("title", "")) or ""
            title = re.sub(r"<[^>]+>", "", title).strip()
            if not title:
                continue
            label_str = f"[{label}] {title}"
            if with_age:
                if is_atom:
                    pub_raw = item.findtext(f"{ATOM}published", "") or item.findtext(f"{ATOM}updated", "")
                else:
                    pub_raw = item.findtext("pubDate", "")
                age_hours = 999
                try:
                    age_hours = (now_utc - parsedate_to_datetime(pub_raw)).total_seconds() / 3600
                except Exception:
                    try:
                        pub_dt = datetime.fromisoformat(pub_raw.replace("Z", "+00:00"))
                        age_hours = (now_utc - pub_dt).total_seconds() / 3600
                    except Exception:
                        pass
                results.append((label_str, age_hours))
            else:
                results.append(label_str)
        return results
    except Exception as e:
        print(f"[WARN] RSS fetch failed ({label}): {e}")
        return []


def discover_topic(client, state: ClientState):
    """Pick the single best trending topic for this client's niche/audience."""
    print(f"[SEARCH] [{client.id}] Discovering today's topic...")
    headlines = []
    src = client.sources

    for feed_url, label in src.company_feeds:
        headlines += fetch_rss_titles(feed_url, label=label, limit=3)
    for feed_url, label in src.blog_feeds:
        headlines += fetch_rss_titles(feed_url, label=label, limit=3)
    for cid, label in src.youtube_channels:
        headlines += fetch_rss_titles(
            f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}", label=label, limit=2)

    geo = client.geo
    google_url = (f"https://news.google.com/rss/search?q={quote(src.news_query)}"
                  f"&hl=en-{geo}&gl={geo}&ceid={geo}:en")
    headlines += fetch_rss_titles(google_url, label="GOOGLE NEWS", limit=5)
    headlines += fetch_rss_titles(
        f"https://trends.google.com/trends/trendingsearches/daily/rss?geo={geo}",
        label="TRENDING", limit=5)

    if not headlines:
        print("[WARN] No headlines gathered.")
        return None

    seen, unique = set(), []
    for h in headlines:
        if h not in seen:
            seen.add(h)
            unique.append(h)

    used = state.load_used_topics()
    used_clean = [l.split(" | ", 1)[-1] if " | " in l else l for l in used]
    used_text = "\n".join(used_clean[-30:]) if used_clean else "None yet."

    prompt = f"""You are an SEO content strategist for {client.brand.name}, serving {client.audience} in {client.geo_label}.

TODAY'S HEADLINES (AI blogs, top marketing blogs, Google News, Google Trends {client.geo_label}):
{chr(10).join(unique[:25])}

TOPICS ALREADY WRITTEN — DO NOT repeat or closely imitate any of these:
{used_text}

Pick the SINGLE best blog topic from today's headlines for this audience.
Priority: (1) breaking AI/industry news, (2) a newly launched tool useful to them,
(3) a trending SEO/marketing/strategy angle, (4) a highly shareable, curiosity-driven idea.
Always reframe for {client.audience} in {client.geo_label}.

Respond with ONLY the blog topic phrase (5 to 10 words). No explanation, no punctuation at end, no quotes."""

    topic = call_ai(messages=[{"role": "user", "content": prompt}],
                    max_tokens=60, tier="fast").strip(".").strip('"').strip("'")

    if topic and state.is_duplicate(topic, used):
        print("[WARN] Topic too similar to recent posts.")
        return None
    print(f"[OK] Discovered topic: {topic}")
    return topic or None


def detect_breaking_news(client, state: ClientState, max_age_hours=1.5):
    """Scan the client's breaking feeds for a fresh (<max_age_hours) announcement."""
    print(f"[BREAKING] [{client.id}] Scanning last {max_age_hours}h...")
    fresh = []
    for feed_url, label in client.sources.breaking_feeds:
        for headline, age in fetch_rss_titles(feed_url, label=label, limit=5, with_age=True):
            if age <= max_age_hours:
                fresh.append((headline, age))

    if not fresh:
        print("[BREAKING] No breaking news found.")
        return None
    fresh.sort(key=lambda x: x[1])

    posted = state.load_posted_headlines()
    fresh = [(h, a) for (h, a) in fresh if state.headline_sig(h) not in posted]
    if not fresh:
        print("[BREAKING] All fresh headlines already covered.")
        return None

    used = state.load_used_topics()
    used_clean = [l.split(" | ", 1)[-1] if " | " in l else l for l in used]
    prompt = f"""You are an SEO content strategist for {client.brand.name}, serving {client.audience} in {client.geo_label}.

BREAKING HEADLINES (last {max_age_hours} hours):
{chr(10).join(h for h, _ in fresh[:10])}

ALREADY WRITTEN — do not repeat:
{chr(10).join(used_clean[-30:]) if used_clean else "None yet."}

Write an urgent BREAKING NEWS blog topic for {client.audience}, reframed for {client.geo_label}.
Respond with ONLY the topic phrase (5 to 12 words). No explanation, no end punctuation, no quotes."""

    topic = call_ai(messages=[{"role": "user", "content": prompt}],
                    max_tokens=60, tier="fast").strip(".").strip('"').strip("'")
    if topic and state.is_duplicate(topic, used):
        print("[BREAKING] Topic too similar to a recent post.")
        return None
    state.record_posted_headlines([state.headline_sig(h) for h, _ in fresh[:10]])
    print(f"[BREAKING] Topic selected: {topic}")
    return topic or None
