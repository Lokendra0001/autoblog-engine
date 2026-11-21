"""Strapi CMS (v5) upload to a blog collection, with duplicate protection.

The collection and its field names come from the client config (`strapi.collection`, `strapi.fields`).

Before anything is uploaded the existing blogs (published AND drafts) are read; an article whose
slug or topic already exists is never uploaded again. If the blog list cannot be read, nothing is
uploaded (it is retried later) — better a late article than a duplicate one.
"""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path

import requests

from .state import ClientState

_TIMEOUT = 30


def enabled(client) -> bool:
    return bool(client.strapi.url and client.strapi.token)


def _api(client, path: str) -> str:
    return client.strapi.url.rstrip("/") + path


def _coll(client, doc_id: str = "") -> str:
    return _api(client, f"/api/{client.strapi.collection}" + (f"/{doc_id}" if doc_id else ""))


def _auth(client) -> dict:
    return {"Authorization": f"Bearer {client.strapi.token}"} if client.strapi.token else {}


def list_blogs(client) -> list[dict] | None:
    """All blogs in Strapi as [{title, slug, documentId, status}], drafts included when a token is set.
    Returns None if Strapi could not be read (callers must then not upload)."""
    if not client.strapi.url:
        return []
    statuses = ["published", "draft"] if client.strapi.token else ["published"]
    fm = client.strapi.field_map()
    t, s = fm["title"], fm["slug"]
    params = {"fields[0]": t, "fields[1]": s}
    if "image" in fm:
        params[f"populate[{fm['image']}][fields][0]"] = "url"
    blogs, seen = [], set()
    try:
        for status in statuses:
            page = 1
            while True:
                r = requests.get(_coll(client), headers=_auth(client), timeout=_TIMEOUT, params={
                    **params, "status": status, "pagination[page]": page, "pagination[pageSize]": 100})
                r.raise_for_status()
                body = r.json()
                for b in body.get("data", []):
                    if b["documentId"] not in seen:  # a published post also has a draft version
                        seen.add(b["documentId"])
                        blogs.append({"title": b.get(t) or "", "slug": b.get(s) or "",
                                      "documentId": b["documentId"], "status": status,
                                      "has_image": bool(b.get(fm.get("image", "")))})
                if page >= body.get("meta", {}).get("pagination", {}).get("pageCount", 1):
                    break
                page += 1
        return blogs
    except Exception as e:
        print(f"[WARN] Could not read blogs from Strapi: {e}")
        return None


def find_existing(blogs: list[dict], *, title: str = "", slug: str = "", keyword: str = "") -> dict | None:
    """The existing blog this article would duplicate (same slug, or same topic), or None."""
    for b in blogs:
        if slug and b["slug"] == slug:
            return b
        if any(text and ClientState.similar(text, b["title"]) for text in (title, keyword)):
            return b
    return None


def _upload_image(client, path: Path, alt: str) -> int | None:
    try:
        with path.open("rb") as f:
            r = requests.post(_api(client, "/api/upload"), headers=_auth(client), timeout=120,
                              files={"files": (path.name, f, mimetypes.guess_type(path.name)[0] or "image/jpeg")},
                              data={"fileInfo": json.dumps({"name": path.name, "alternativeText": alt})})
        r.raise_for_status()
        return r.json()[0]["id"]
    except Exception as e:
        print(f"[WARN] Strapi image upload failed: {e}")
        return None


def upload_article(client, data: dict, image_path: Path | None) -> dict:
    """Upload one exported article. Returns {"result": "uploaded"|"exists"|"failed", ...}."""
    if not enabled(client):
        return {"result": "failed", "reason": "Strapi url/token not configured"}
    blogs = list_blogs(client)
    if blogs is None:
        return {"result": "failed", "reason": "could not read existing blogs (not uploading, to avoid duplicates)"}
    existing = find_existing(blogs, title=data["title"], slug=data["slug"], keyword=data.get("focus_keyword", ""))
    if existing:
        print(f"[STRAPI] Already on the site, not uploading: {existing['title']} ({existing['status']})")
        res = {"result": "exists", "documentId": existing["documentId"], "title": existing["title"],
               "status": existing["status"], "slug": existing["slug"]}
        # Our own earlier upload (same slug) that went up without a cover: add the cover now.
        if existing["slug"] == data["slug"] and not existing.get("has_image") and image_path and image_path.is_file():
            res["cover_added"] = set_cover(client, existing, image_path, data["title"])
        return res

    image_id = _upload_image(client, image_path, data["title"]) if image_path and image_path.is_file() else None
    fields = {}
    for key, name in client.strapi.field_map().items():
        value = image_id if key == "image" else data.get(key)
        if value not in (None, "", []):
            fields[name] = ", ".join(value) if key == "tags" and isinstance(value, list) else value
    status = "published" if client.strapi.status == "published" else "draft"
    try:
        r = requests.post(_coll(client), params={"status": status}, json={"data": fields},
                          headers=_auth(client), timeout=_TIMEOUT)
        if r.status_code >= 400:
            return {"result": "failed", "reason": f"HTTP {r.status_code}: {r.text[:300]}"}
        doc = r.json()["data"]["documentId"]
    except Exception as e:
        return {"result": "failed", "reason": str(e)[:300]}
    url = f"{client.brand.website.rstrip('/')}{client.strapi.blog_path}/{data['slug']}"
    print(f"[STRAPI] Uploaded as {status}: {data['title']}" + (f" -> {url}" if status == "published" else ""))
    return {"result": "uploaded", "documentId": doc, "status": status, "url": url, "image": bool(image_id)}


def set_cover(client, blog: dict, image_path: Path, alt: str) -> bool:
    """Attach a cover image to an existing blog (needs the token's `update` permission)."""
    name = client.strapi.field_map().get("image")
    image_id = _upload_image(client, image_path, alt) if name else None
    if not image_id:
        return False
    r = requests.put(_coll(client, blog["documentId"]), params={"status": blog["status"]},
                     json={"data": {name: image_id}}, headers=_auth(client), timeout=_TIMEOUT)
    if r.status_code >= 400:
        print(f"[WARN] Could not attach the cover (HTTP {r.status_code}). If 403: give the API token the "
              f"'update' permission on the collection, or upload {image_path.name} in the admin.")
        return False
    print(f"[STRAPI] Cover image added to: {blog['title']}")
    return True


def check(client) -> tuple[bool, str]:
    """Can we read (incl. drafts) with this token? Used by `cli.py validate`."""
    if not client.strapi.url:
        return False, "strapi.url not set"
    if not client.strapi.token:
        return False, "STRAPI_API_TOKEN not set (articles will only be saved as previews)"
    try:
        r = requests.get(_coll(client), headers=_auth(client), timeout=_TIMEOUT,
                         params={"status": "draft", "pagination[pageSize]": 1})
        if r.status_code == 200:
            return True, f"token OK, {r.json()['meta']['pagination']['total']} draft blog(s)"
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, str(e)
