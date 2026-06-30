"""WordPress publishing: REST API post, categories/tags, media, JSON-LD schema.

All WP credentials come from the per-client config, so one engine publishes to
any number of client WordPress sites.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone

import requests

_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _auth(client):
    return (client.wordpress.username, client.wordpress.app_password)


def _wp(method, url, max_retries=4, **kwargs):
    headers = kwargs.get("headers", {}).copy()
    headers.setdefault("User-Agent", _BROWSER_UA)
    kwargs["headers"] = headers
    resp = None
    for attempt in range(max_retries):
        resp = method(url, **kwargs)
        if resp.status_code != 429:
            return resp
        wait = int(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
        print(f"[WARN] WP rate limit (429). Waiting {wait}s...")
        time.sleep(wait)
    return resp


def get_or_create_term(client, taxonomy, name):
    endpoint = f"{client.wordpress.site_url}/wp-json/wp/v2/{taxonomy}"
    r = _wp(requests.post, endpoint, json={"name": name}, auth=_auth(client), timeout=15)
    if r.status_code in (200, 201):
        return r.json().get("id")
    r2 = _wp(requests.get, endpoint, params={"search": name, "per_page": 1}, auth=_auth(client), timeout=15)
    if r2.status_code == 200 and r2.json():
        return r2.json()[0].get("id")
    print(f"[WARN] Could not get/create {taxonomy}: {name}")
    return None


def upload_image_bytes(client, image_bytes, seed, alt_text="", caption=""):
    try:
        filename = re.sub(r"[^a-z0-9]+", "-", seed.lower())[:60].strip("-") + ".jpg"
        r = _wp(requests.post, f"{client.wordpress.site_url}/wp-json/wp/v2/media",
                data=image_bytes, auth=_auth(client), timeout=60,
                headers={"Content-Type": "image/jpeg",
                         "Content-Disposition": f'attachment; filename="{filename}"'})
        if r.status_code not in (200, 201):
            print(f"[WARN] WP media upload failed: {r.status_code}")
            return None, None
        media_id = r.json().get("id")
        src = r.json().get("source_url")
        _wp(requests.post, f"{client.wordpress.site_url}/wp-json/wp/v2/media/{media_id}",
            json={"alt_text": alt_text or seed, "caption": caption}, auth=_auth(client), timeout=20)
        return media_id, src
    except Exception as e:
        print(f"[WARN] Image bytes upload error: {e}")
        return None, None


def upload_image_url(client, image_url, seed, photographer="Pexels"):
    try:
        img = requests.get(image_url, timeout=30)
        if img.status_code != 200:
            return None, None
        return upload_image_bytes(client, img.content, seed,
                                  alt_text=seed, caption=f"Photo by {photographer} via Pexels")
    except Exception as e:
        print(f"[WARN] Image url upload error: {e}")
        return None, None


def publish_post(client, title, content, meta, focus_keyword, category, tags, featured_media_id=None):
    print(f"[OK] [{client.id}] Publishing to WordPress...")
    cat_id = get_or_create_term(client, "categories", category)
    tag_ids = []
    for tag in (tags or [])[:10]:
        tid = get_or_create_term(client, "tags", tag)
        if tid:
            tag_ids.append(tid)
        time.sleep(0.4)

    payload = {
        "title": title, "content": content, "excerpt": meta, "status": "publish",
        "categories": [cat_id] if cat_id else [], "tags": tag_ids,
        "featured_media": featured_media_id or 0,
        "meta": {
            "_yoast_wpseo_focuskw": focus_keyword, "_yoast_wpseo_metadesc": meta,
            "rank_math_focus_keyword": focus_keyword, "rank_math_description": meta,
        },
    }
    r = _wp(requests.post, f"{client.wordpress.site_url}/wp-json/wp/v2/posts",
            json=payload, auth=_auth(client), timeout=60)
    if r.status_code in (200, 201):
        data = r.json()
        print(f"[OK] Published! ID {data.get('id')} -> {data.get('link')}")
        return data.get("id"), data.get("link")
    raise Exception(f"WP publish failed {r.status_code}: {r.text[:300]}")


def patch_content(client, post_id, content):
    r = _wp(requests.post, f"{client.wordpress.site_url}/wp-json/wp/v2/posts/{post_id}",
            json={"content": content}, auth=_auth(client), timeout=30)
    if r.status_code in (200, 201):
        print("[OK] Post content patched (schema injected)")
    else:
        print(f"[WARN] Patch failed: {r.status_code}")


def build_schema(client, title, meta, content, post_url):
    """Prepend Article + FAQPage + HowTo JSON-LD parsed from the HTML."""
    import json
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    logo_url = f"{client.brand.website.rstrip('/')}/assets/logo.png"
    schemas = [{
        "@context": "https://schema.org", "@type": "Article",
        "headline": title, "description": meta,
        "author": {"@type": "Organization", "name": client.brand.name, "url": client.brand.website},
        "publisher": {"@type": "Organization", "name": client.brand.name,
                      "logo": {"@type": "ImageObject", "url": logo_url}},
        "datePublished": now, "dateModified": now,
        "mainEntityOfPage": {"@type": "WebPage", "@id": post_url},
    }]

    questions = re.findall(r'<summary[^>]*class="navigo-faq-summary"[^>]*>(.*?)</summary>', content, re.DOTALL)
    answers = re.findall(r'<div[^>]*class="navigo-faq-answer"[^>]*>(.*?)</div>', content, re.DOTALL)
    faq = []
    for q, a in zip(questions, answers):
        qt, at = re.sub(r"<[^>]+>", "", q).strip(), re.sub(r"<[^>]+>", "", a).strip()
        if qt and at:
            faq.append({"@type": "Question", "name": qt,
                        "acceptedAnswer": {"@type": "Answer", "text": at}})
    if faq:
        schemas.append({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": faq})

    schema_html = "\n".join(
        f'<script type="application/ld+json">{json.dumps(s, ensure_ascii=False)}</script>' for s in schemas)
    return schema_html + "\n" + content
