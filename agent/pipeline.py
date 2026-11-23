"""Orchestrates one article for a client.

preview_article: duplicate check -> research -> write -> stock images -> export (.json) + preview (.html)
                 -> upload to Strapi / WordPress unless the destination is files.
run_once:        one article now (CLI `run`).

Where articles go is `client.destination`: strapi, wordpress or files (saved only).
"""

from __future__ import annotations

import html
import json
import re

import requests
import webbrowser
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import images, indexer, publisher, research as research_mod, strapi, trends, writer
from .state import ClientState

_PLACEHOLDER = re.compile(r"\[IMAGE_PLACEHOLDER:\s*(.*?)\]")


def slugify(text: str) -> str:
    """Same rule as the website admin's slug field."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def read_time(content: str) -> str:
    words = len(writer.text_of(re.sub(r"<script.*?</script>", "", content, flags=re.S)).split())
    return f"{max(1, round(words / 200))} min read"


def _figure(url, alt, credit_html):
    return (f'<figure style="margin:32px 0;"><img src="{url}" alt="{html.escape(alt)}" '
            f'style="width:100%;height:auto;border-radius:12px;" loading="lazy"/>'
            f'<figcaption style="font-size:13px;color:#6b7280;margin-top:8px;text-align:center;">'
            f'{credit_html}</figcaption></figure>')


def _fill_images(content: str, resolve, keyword: str = "") -> str:
    """Replace the first 2 placeholders using resolve(query) -> (url, credit_html); drop the rest.
    Alt text = photo description + focus keyword (SEO checkers look for the keyword in alt)."""
    def sub(m):
        query = m.group(1).strip()
        url, credit = resolve(query)
        alt = f"{query.capitalize()}, {keyword}" if keyword and keyword.lower() not in query.lower() else query
        return _figure(url, alt, credit) if url else ""
    content = _PLACEHOLDER.sub(sub, content, count=2)
    return _PLACEHOLDER.sub("", content)


def _hotlink(query):
    url, credit, _ = images.fetch_stock_image(query)
    return url, credit


# ── export + preview ──────────────────────────────────────────────────────────

def _download_cover(client, url: str, name: str) -> str:
    """Save the cover photo as <name>.jpg next to the drafts, ready to upload in the admin.
    Returns the file name ("" on failure). The keyword in the file name helps image SEO."""
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0 (compatible; AutoBlogEngine/1.0)"})
        r.raise_for_status()
        out = client.drafts_dir
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{name}.jpg").write_bytes(r.content)
        return f"{name}.jpg"
    except Exception as e:
        print(f"[WARN] Cover download failed: {e}")
        return ""


def build_export(client, article: writer.Article, publish_date: str) -> dict:
    """The article as the website's blog fields (+ SEO extras), with images resolved."""
    print("[IMAGE] Fetching images from Unsplash")
    content = _fill_images(article.content, _hotlink, article.focus_keyword)
    image, credit_html, credit_text = images.fetch_stock_image(article.featured_query or article.focus_keyword)
    image_file = _download_cover(client, image, slugify(article.title)) if image else ""
    if credit_html:  # Unsplash asks for visible attribution
        content += f'\n<p style="font-size:13px;color:#6b7280;">Cover image: {credit_html}</p>'
    return {
        "title": article.title,
        "slug": slugify(article.title),
        "category": article.category,
        "readTime": read_time(content),
        "date": publish_date,
        "image": image or "",
        "imageFile": image_file,
        "imageSource": credit_text or "",
        "content": content,
        "meta_description": article.meta,
        "focus_keyword": article.focus_keyword,
        "tags": article.tags,
        "review": {"score": article.review_score, "notes": article.review_notes},
        "client": client.id,
        "generated": datetime.now().isoformat(timespec="seconds"),
    }


_PREVIEW_CSS = """
*{box-sizing:border-box} body{margin:0;font-family:'DM Sans',system-ui,sans-serif;color:#4b5563;background:#fff}
.bar{position:sticky;top:0;z-index:10;background:#0f172a;color:#e2e8f0;font-size:13px;padding:10px 16px}
.bar details>summary{cursor:pointer;font-weight:600;color:#fff}
.bar .grid{display:grid;grid-template-columns:140px 1fr auto;gap:6px 12px;align-items:center;margin-top:10px;max-width:1100px}
.bar .k{color:#94a3b8} .bar .v{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#fff}
.bar button{background:#facc15;color:#0f172a;border:0;border-radius:6px;padding:4px 10px;font-weight:600;cursor:pointer;font-size:12px}
.bar .note{color:#94a3b8;margin-top:8px}
.wrap{max-width:1200px;margin:0 auto;padding:40px 16px 80px}
.cat{display:inline-block;border:1px solid #e2e8f0;border-radius:999px;padding:8px 16px;font-size:12px;font-weight:600;
 text-transform:uppercase;letter-spacing:.05em;color:#014ca9;margin-bottom:20px}
h1.t{font-size:clamp(2.2rem,5vw,3.6rem);line-height:1.1;color:#0f172a;margin:0 0 20px}
.info{display:flex;gap:24px;font-size:14px;font-weight:500;margin-bottom:40px}
.hero{width:100%;height:clamp(300px,45vw,600px);object-fit:cover;border-radius:15px;background:#f1f5f9;margin-bottom:56px}
.c{max-width:1150px;margin:0 auto;overflow-wrap:break-word}
.c h2{font-size:1.875rem;color:#0f172a;margin:48px 0 24px} .c h3{font-size:1.5rem;color:#0f172a;margin:32px 0 16px}
.c p,.c ul,.c ol{font-size:1.125rem;line-height:1.65;margin:0 0 24px} .c ul,.c ol{padding-left:24px} .c li{padding-left:8px;margin-bottom:8px}
.c strong{color:#0f172a} .c a{color:#014ca9}
.c blockquote{border-left:4px solid #eab308;padding:4px 16px;margin:0 0 24px;font-size:1.25rem;font-style:italic;
 color:rgba(1,76,169,.8);background:#f8fafc;border-radius:0 8px 8px 0}
"""


def _preview_html(client, data: dict) -> str:
    fields = [("Title", "title"), ("Slug", "slug"), ("Category", "category"), ("Read time", "readTime"),
              ("Date", "date"), ("Image URL", "image"), ("Image source", "imageSource"),
              ("Content (HTML)", "content"), ("Meta description", "meta_description"),
              ("Focus keyword", "focus_keyword")]
    rows = "".join(
        f'<div class="k">{label}</div><div class="v">{html.escape(writer.text_of(data[key])[:140])}</div>'
        f'<button data-k="{key}">Copy</button>' for label, key in fields)
    # JSON inside <script> must not contain "</" (it would close the tag early).
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    hero = f'<img class="hero" src="{data["image"]}" alt="{html.escape(data["title"])}">' if data["image"] else ""
    if data.get("imageFile"):  # relative link: works from disk and from the local web page
        f = html.escape(data["imageFile"])
        rows += (f'<div class="k">Cover image file</div><div class="v">{f}</div>'
                 f'<a href="{f}" download="{f}"><button type="button">Download</button></a>')
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(data["title"])}</title>
<meta name="description" content="{html.escape(data["meta_description"])}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{_PREVIEW_CSS}</style></head><body>
<div class="bar"><details open><summary>Blog fields for the {html.escape(client.brand.name)} admin (click to hide)</summary>
<div class="grid">{rows}</div>
<div class="note">Image: click Download next to "Cover image file" and upload that file in the admin (its name contains the keyword). Paste "Content (HTML)" into the content field.</div>
</details></div>
<div class="wrap">
<div class="cat">{html.escape(data["category"])}</div>
<h1 class="t">{html.escape(data["title"])}</h1>
<div class="info"><span>{data["date"]}</span><span>{data["readTime"]}</span></div>
{hero}
<div class="c">{data["content"]}</div>
</div>
<script id="data" type="application/json">{payload}</script>
<script>
const DATA = JSON.parse(document.getElementById("data").textContent);
document.querySelectorAll(".bar button").forEach(b => b.onclick = async () => {{
  const text = String(DATA[b.dataset.k] ?? "");
  try {{ await navigator.clipboard.writeText(text); }}
  catch (e) {{ const t = document.createElement("textarea"); t.value = text; document.body.appendChild(t);
               t.select(); document.execCommand("copy"); t.remove(); }}
  const old = b.textContent; b.textContent = "Copied"; setTimeout(() => b.textContent = old, 1200);
}});
</script></body></html>"""


def save_article(client, data: dict):
    """Write <stamp>-<slug>.json (export) and .html (preview) to data/<client>/drafts/. Returns the .html path."""
    out = client.drafts_dir
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now().strftime('%Y%m%d-%H%M')}-{data['slug'][:60].strip('-')}"
    (out / f"{stem}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    path = out / f"{stem}.html"
    path.write_text(_preview_html(client, data), encoding="utf-8")
    return path


class AlreadyOnSite(Exception):
    """The topic is already a blog on the website (published or draft)."""


def site_titles(client) -> list[str]:
    """Titles of the blogs already in Strapi (empty if not configured or unreadable)."""
    return [b["title"] for b in (strapi.list_blogs(client) or [])]


def upload_saved(client, path, status: str | None = None) -> dict:
    """Upload a saved article (its .json export + cover file) to the client's destination (Strapi or
    WordPress) and record the result in the .json. Only call when client.destination != "files".
    `status` ("draft"/"published") overrides the configured default for this one article."""
    json_path = path.with_suffix(".json")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if not data.get("imageFile") and data.get("image"):  # older drafts: fetch the cover now
        data["imageFile"] = _download_cover(client, data["image"], data["slug"])
    image = (json_path.parent / data["imageFile"]) if data.get("imageFile") else None
    dest = client.destination
    upload = strapi.upload_article if dest == "strapi" else publisher.upload_article
    res = {**upload(client, data, image, status=status), "to": dest}
    data.pop("strapi", None)  # older exports kept the result under this name
    data["upload"] = res
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    if res["result"] == "failed":
        print(f"[WARN] Upload to {dest} failed: {res['reason']}")
    elif res["result"] == "uploaded" and res["status"] == "published":
        _went_live(client, data, res["url"])
    return res


def _went_live(client, data: dict, url: str) -> None:
    """Record a newly live article and ask search engines to index it."""
    ClientState(client).log_published({"ts": datetime.now(timezone.utc).isoformat(), "title": data["title"],
                                       "url": url, "category": data["category"], "to": client.destination})
    try:
        indexer.ping_all(client, url)
    except Exception as e:
        print(f"[WARN] Indexing ping failed: {e}")


def uploaded_draft(client, draft_name: str) -> dict | None:
    """The CMS upload of a saved article if it is our own upload, else None.
    Returns the .json's "upload" record: {"result": "uploaded", "documentId", "status", ...}."""
    if not draft_name or "/" in draft_name or "\\" in draft_name:
        return None
    path = (client.drafts_dir / draft_name).with_suffix(".json")
    try:
        up = json.loads(path.read_text(encoding="utf-8")).get("upload") or {}
    except (OSError, ValueError):
        return None
    # "exists" means the topic was already on the site: that document is not ours to publish.
    return up if up.get("result") == "uploaded" and up.get("documentId") else None


def publish_saved(client, draft_name: str) -> dict:
    """Publish an article that was uploaded as a draft. Returns {"result": "published", "url"} or
    {"result": "failed", "reason"}; the .json export is updated on success."""
    up = uploaded_draft(client, draft_name)
    if not up:
        return {"result": "failed", "reason": "this article was not uploaded to the CMS by this app"}
    if up.get("status") == "published":
        return {"result": "failed", "reason": "already published"}
    path = (client.drafts_dir / draft_name).with_suffix(".json")
    data = json.loads(path.read_text(encoding="utf-8"))
    if client.destination == "strapi":
        if strapi.status_of(client, up["documentId"]) == "published":  # published in the admin meanwhile
            res = {"result": "published", "url": f"{client.brand.website.rstrip('/')}{client.strapi.blog_path}/{data['slug']}"}
        else:
            res = strapi.publish(client, up["documentId"], data["slug"])
    elif client.destination == "wordpress":
        res = publisher.publish(client, up["documentId"])
    else:
        return {"result": "failed", "reason": "articles are saved as files only"}
    if res["result"] == "published":
        data["upload"] = {**up, "status": "published", "url": res["url"] or up.get("url", "")}
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        _went_live(client, data, data["upload"]["url"])
    return res


def preview_article(client, keyword, brief="", publish_date: str | None = None, upload: bool = True,
                    status: str | None = None):
    """Research + write one article, save it to data/<client>/drafts/ and (unless the destination is
    "files" or upload=False) upload it to Strapi or WordPress.

    Raises AlreadyOnSite before spending any AI quota if the topic is already a blog on the site.
    `brief` is optional editorial direction (e.g. the angle from the monthly plan);
    `publish_date` (YYYY-MM-DD) defaults to today. Returns {"path", "title", "data", "upload"?}.
    """
    hit = strapi.find_existing(strapi.list_blogs(client) or [], keyword=keyword)
    if hit:
        raise AlreadyOnSite(f'"{hit["title"]}" is already on the site ({hit["status"]})')
    research_text = research_mod.research_topic(client, keyword)
    if brief:
        research_text = f"ARTICLE BRIEF (follow this angle): {brief}\n\n{research_text}"
    article = writer.generate_blog(client, keyword, research_text)
    today = datetime.now(ZoneInfo(client.timezone)).date().isoformat()
    data = build_export(client, article, publish_date or today)
    print(f"[OK] {data['title']} | {data['readTime']} | {data['category']}")
    path = save_article(client, data)
    ClientState(client).save_used_topic(keyword)
    print(f"[SAVED] {path}")
    result = {"path": path, "title": data["title"], "data": data}
    if upload and client.destination != "files":
        result["upload"] = upload_saved(client, path, status=status)
    return result


# ── single run (CLI `run`) ────────────────────────────────────────────────────

def _pick_topic(client, state):
    if client.topic_mode == "breaking":
        return trends.detect_breaking_news(client, state)
    if client.topic_mode == "evergreen_queue":
        return state.next_queued_keyword()
    return trends.discover_topic(client, state) or state.next_queued_keyword()


def run_once(client, keyword=None, dry_run=False):
    """Write one article now (CLI `run`). dry_run: save and open the preview, never upload."""
    state = ClientState(client)
    keyword = keyword or _pick_topic(client, state)
    if not keyword:
        print("[WARN] No topic available.")
        return None
    print(f"[TOPIC] {keyword}")
    try:
        result = preview_article(client, keyword, upload=not dry_run)
    except AlreadyOnSite as e:
        print(f"[SKIP] {e}")
        return None
    if dry_run:
        webbrowser.open(result["path"].as_uri())
    return {"keyword": keyword, "draft": str(result["path"]), "upload": result.get("upload")}
