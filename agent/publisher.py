"""WordPress publishing (optional): REST API post, categories/tags, media, Article schema.

All WP credentials come from the per-client config, so one engine publishes to
any number of client WordPress sites.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

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


def upload_image_url(client, image_url, seed, credit):
    try:
        img = requests.get(image_url, timeout=30, headers={"User-Agent": "Mozilla/5.0 (compatible; AutoBlogEngine/1.0)"})
        if img.status_code != 200:
            return None, None
        return upload_image_bytes(client, img.content, seed,
                                  alt_text=seed, caption=credit)
    except Exception as e:
        print(f"[WARN] Image url upload error: {e}")
        return None, None


def publish_post(client, title, content, meta, focus_keyword, category, tags, featured_media_id=None,
                 status="publish", slug=None):
    print(f"[OK] [{client.id}] Publishing to WordPress...")
    cat_id = get_or_create_term(client, "categories", category)
    tag_ids = []
    for tag in (tags or [])[:10]:
        tid = get_or_create_term(client, "tags", tag)
        if tid:
            tag_ids.append(tid)
        time.sleep(0.4)

    payload = {
        "title": title, "content": content, "excerpt": meta, "status": status,
        "categories": [cat_id] if cat_id else [], "tags": tag_ids,
        "featured_media": featured_media_id or 0,
        "meta": {
            "_yoast_wpseo_focuskw": focus_keyword, "_yoast_wpseo_metadesc": meta,
            "rank_math_focus_keyword": focus_keyword, "rank_math_description": meta,
        },
    }
    if slug:
        payload["slug"] = slug
    r = _wp(requests.post, f"{client.wordpress.site_url}/wp-json/wp/v2/posts",
            json=payload, auth=_auth(client), timeout=60)
    if r.status_code in (200, 201):
        data = r.json()
        print(f"[OK] Published! ID {data.get('id')} -> {data.get('link')}")
        return data.get("id"), data.get("link")
    raise Exception(f"WP publish failed {r.status_code}: {r.text[:300]}")


def upload_article(client, data: dict, image_path: Path | None, status: str | None = None) -> dict:
    """Post one exported article (see pipeline.build_export) to WordPress.
    Returns the same shape as strapi.upload_article: {"result": "uploaded"|"failed", ...}."""
    status = "publish" if (status or client.wordpress.publish_status) == "published" else "draft"
    meta, keyword = data.get("meta_description", ""), data.get("focus_keyword", "")
    try:
        media_id = None
        if image_path and image_path.is_file():
            media_id, _ = upload_image_bytes(client, image_path.read_bytes(), data["slug"],
                                             alt_text=keyword or data["title"], caption=data.get("imageSource", ""))
        post_id, url = publish_post(client, data["title"], data["content"], meta, keyword, data["category"],
                                    data.get("tags"), media_id, status=status, slug=data["slug"])
        patch_content(client, post_id, build_schema(client, data["title"], meta, data["content"], url))
    except Exception as e:
        return {"result": "failed", "reason": str(e)[:300]}
    return {"result": "uploaded", "documentId": str(post_id), "url": url, "image": bool(media_id),
            "status": "published" if status == "publish" else "draft"}


def publish(client, post_id: str) -> dict:
    """Publish an existing WordPress draft. Same result shape as strapi.publish."""
    try:
        r = _wp(requests.post, f"{client.wordpress.site_url}/wp-json/wp/v2/posts/{post_id}",
                json={"status": "publish"}, auth=_auth(client), timeout=30)
    except Exception as e:
        return {"result": "failed", "reason": str(e)[:300]}
    if r.status_code not in (200, 201):
        return {"result": "failed", "reason": f"HTTP {r.status_code}: {r.text[:200]}"}
    return {"result": "published", "url": r.json().get("link", "")}


def admin_url(client, post_id: str) -> str:
    return f"{client.wordpress.site_url.rstrip('/')}/wp-admin/post.php?post={post_id}&action=edit"


def patch_content(client, post_id, content):
    r = _wp(requests.post, f"{client.wordpress.site_url}/wp-json/wp/v2/posts/{post_id}",
            json={"content": content}, auth=_auth(client), timeout=30)
    if r.status_code in (200, 201):
        print("[OK] Post content patched (schema injected)")
    else:
        print(f"[WARN] Patch failed: {r.status_code}")


def build_schema(client, title, meta, content, post_url):
    """Prepend Article JSON-LD. (FAQPage JSON-LD is already part of the generated content.)"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    org = {"@type": "Organization", "name": client.brand.name, "url": client.brand.website}
    schema = {
        "@context": "https://schema.org", "@type": "Article",
        "headline": title, "description": meta, "author": org, "publisher": org,
        "datePublished": now, "dateModified": now,
        "mainEntityOfPage": {"@type": "WebPage", "@id": post_url},
    }
    return f'<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False)}</script>\n{content}'
