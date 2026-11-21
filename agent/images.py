"""Stock photos from Unsplash (free API key, attribution required)."""

from __future__ import annotations

import os

import requests

UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")

_UA = {"User-Agent": "Mozilla/5.0 (compatible; AutoBlogEngine/1.0)"}


def _match(query, photo) -> int:
    """How many query words appear in the photo's descriptions/tags (Unsplash's own ranking is loose)."""
    text = " ".join([photo.get("description") or "", photo.get("alt_description") or "",
                     *[t.get("title", "") for t in photo.get("tags", [])]]).lower()
    return sum(1 for w in set(query.lower().split()) if len(w) > 2 and w in text)


def fetch_stock_image(keyword):
    """Stock photo from Unsplash (free API, attribution required).

    Returns (image_url, credit_html, credit_text) or (None, None, None). Also pings Unsplash's
    download endpoint, which their API guidelines require when a photo is used.
    """
    if not UNSPLASH_ACCESS_KEY:
        return None, None, None
    auth = {**_UA, "Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"}
    try:
        # Niche phrases can return nothing, so drop trailing words until something matches.
        words, results = keyword.split()[:6], []
        while words and not results:
            resp = requests.get(
                "https://api.unsplash.com/search/photos",
                headers=auth,
                params={"query": " ".join(words), "per_page": 10,
                        "orientation": "landscape", "content_filter": "high"},
                timeout=15)
            if resp.status_code != 200:
                print(f"[WARN] Unsplash search failed: HTTP {resp.status_code}")
                return None, None, None
            results = resp.json().get("results", [])
            words = words[:-1]
        if not results:
            return None, None, None
        results.sort(key=lambda p: -_match(keyword, p))  # stable: ties keep Unsplash's ranking
        photo = results[0]
        requests.get(photo["links"]["download_location"], headers=auth, timeout=15)
        ref = "utm_source=seo_content_agent&utm_medium=referral"
        user = photo["user"]
        credit = (f'Photo by <a href="{user["links"]["html"]}?{ref}">{user["name"]}</a> '
                  f'on <a href="https://unsplash.com/?{ref}">Unsplash</a>')
        return (photo["urls"]["raw"] + "&w=1600&q=80&fm=jpg&fit=max", credit,
                f'Photo by {user["name"]} on Unsplash ({photo["links"]["html"]})')
    except Exception as e:
        print(f"[WARN] Unsplash fetch failed: {e}")
        return None, None, None
