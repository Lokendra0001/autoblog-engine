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


def _hotlink(query, avoid=()):
    url, credit, _ = images.fetch_stock_image(query, avoid)
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
    avoid = client.image_avoid
    content = _fill_images(article.content, lambda q: _hotlink(q, avoid), article.focus_keyword)
    image, credit_html, credit_text = images.fetch_stock_image(article.featured_query or article.focus_keyword, avoid)
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
*{box-sizing:border-box;margin:0;padding:0} body{font-family:'DM Sans',system-ui,sans-serif;color:#4b5563;background:#fff}
button{font:inherit;cursor:pointer}
/* Admin panel above the article: what to paste into the CMS, SEO checks and the editor's review */
.tb{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:16px;height:56px;padding:0 24px;
 background:var(--deep);color:#fff;border-top:4px solid var(--primary)}
.tb a.back{display:inline-flex;align-items:center;gap:8px;color:#cbd5e1;text-decoration:none;font-size:13px;font-weight:500}
.tb a.back:hover{color:#fff} .tb .sep{width:1px;height:22px;background:rgba(255,255,255,.18)}
.tb .lbl{font-size:11px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--accent)}
.tb .tt{flex:1;min-width:0;font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tb .acts{display:flex;gap:8px}
.b{height:34px;padding:0 14px;font-size:13px;font-weight:600;border:1px solid rgba(255,255,255,.35);background:transparent;color:#fff}
.b:hover{background:rgba(255,255,255,.1)} .b.pri{background:var(--accent);border-color:var(--accent);color:var(--deep)}
.b.pri:hover{filter:brightness(1.05)}
.adm{background:#f8fafc;border-bottom:1px solid #e2e8f0;padding:24px}
.adm[hidden]{display:none}
.adm-in{max-width:1400px;margin:0 auto;display:grid;gap:20px;grid-template-columns:minmax(0,1fr)}
@media(min-width:1100px){.adm-in{grid-template-columns:minmax(0,1.6fr) minmax(300px,1fr)}}
.card{background:#fff;border:1px solid #e2e8f0}
.card h2{display:flex;align-items:center;justify-content:space-between;gap:12px;height:48px;padding:0 18px;
 border-bottom:1px solid #e2e8f0;font-size:14px;font-weight:700;color:#0f172a}
.card h2 small{font-size:12px;font-weight:500;color:#64748b}
.side{display:grid;gap:20px;align-content:start}
.f{display:grid;grid-template-columns:150px minmax(0,1fr) auto;gap:4px 16px;align-items:center;padding:11px 18px;border-top:1px solid #f1f5f9}
.f:first-of-type{border-top:0}
.f .k{font-size:12px;font-weight:600;color:#64748b}
.f .v{font-size:13.5px;color:#0f172a;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow-wrap:anywhere}
.f .v.mono{font-family:ui-monospace,Menlo,monospace;font-size:12.5px}
.cp{height:28px;padding:0 12px;font-size:12px;font-weight:600;border:1px solid #cbd5e1;background:#fff;color:#0f172a;white-space:nowrap;text-decoration:none;display:inline-flex;align-items:center}
.cp:hover{border-color:var(--primary);color:var(--primary)} .cp.done{background:#f0fdf4;border-color:#86efac;color:#15803d}
.cover{display:grid;grid-template-columns:120px minmax(0,1fr);gap:14px;align-items:center;padding:14px 18px;border-top:1px solid #f1f5f9}
.cover img{width:120px;height:72px;object-fit:cover;background:#f1f5f9}
.cover p{font-size:12.5px;color:#64748b;margin-bottom:8px;overflow-wrap:anywhere}
.chk{list-style:none;padding:6px 0}
.chk li{display:grid;grid-template-columns:22px 1fr auto;gap:10px;align-items:center;padding:8px 18px;font-size:13px;color:#334155}
.chk li b{font-weight:600;color:#0f172a;font-family:ui-monospace,Menlo,monospace;font-size:12px}
.chk i{width:18px;height:18px;display:grid;place-items:center;font-style:normal;font-size:11px;font-weight:700;color:#fff;background:#15803d}
.chk li.no i{background:#b45309}
.score{display:flex;align-items:baseline;gap:6px;padding:16px 18px 6px;font-size:32px;font-weight:800;color:#0f172a}
.score small{font-size:13px;font-weight:500;color:#64748b}
.score.lo{color:#b45309}
.notes{padding:6px 18px 16px 36px;font-size:12.5px;line-height:1.55;color:#475569}
.notes li{margin-top:6px}
.tags{display:flex;flex-wrap:wrap;gap:6px;padding:0 18px 16px}
.tags span{font-size:12px;padding:3px 9px;background:#f1f5f9;color:#334155}
@media(max-width:720px){
 .tb{padding:0 16px;gap:10px} .tb .lbl,.tb .sep,.tb .tt{display:none} .tb .acts{margin-left:auto}
 .adm{padding:16px}
 .f{grid-template-columns:minmax(0,1fr) auto;padding:10px 14px} .f .k{grid-column:1/-1}
}
/* The article, styled like the website's blog page */
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


def _seo_checks(data: dict) -> list[tuple[bool, str, str]]:
    """(passed, label, value) for the checks an SEO plugin will flag first."""
    title, meta, kw = data["title"], data["meta_description"], data["focus_keyword"]
    norm = lambda t: " ".join(re.findall(r"[a-z0-9]+", t.lower()))  # noqa: E731
    return [
        (30 <= len(title) <= 60, "Title length (30-60)", f"{len(title)}"),
        (norm(title).startswith(norm(kw)), "Title starts with keyword", "yes" if norm(title).startswith(norm(kw)) else "no"),
        (120 <= len(meta) <= 160, "Meta description (120-160)", f"{len(meta)}"),
        (norm(kw) in norm(meta), "Keyword in meta description", "yes" if norm(kw) in norm(meta) else "no"),
        (bool(data.get("image")), "Cover image", "found" if data.get("image") else "missing"),
    ]


def preview_page(client, data: dict) -> str:
    """The draft's preview: admin panel (fields, SEO check, review) above the article as the site shows it."""
    fields = [("Title", "title"), ("Slug", "slug"), ("Category", "category"), ("Meta description", "meta_description"),
              ("Focus keyword", "focus_keyword"), ("Read time", "readTime"), ("Date", "date"),
              ("Content (HTML)", "content"), ("Image URL", "image"), ("Image source", "imageSource")]
    rows = "".join(
        f'<div class="f"><div class="k">{label}</div>'
        f'<div class="v{" mono" if key in ("slug", "image", "content") else ""}">{html.escape(writer.text_of(str(data.get(key) or ""))[:220]) or "—"}</div>'
        f'<button class="cp" type="button" data-k="{key}">Copy</button></div>'
        for label, key in fields)
    cover = ""
    if data.get("image"):
        f = html.escape(data.get("imageFile") or "")
        dl = (f'<a class="cp" href="{f}" download="{f}" title="{f}">Download cover image</a>' if f
              else '<p>No cover file saved; use the Image URL above.</p>')
        cover = (f'<div class="cover"><img src="{html.escape(data["image"])}" alt="">'
                 f'<div><p>Upload this file as the cover in the admin; its name contains the keyword.</p>{dl}</div></div>')
    checks = "".join(f'<li class="{"" if ok else "no"}"><i>{"✓" if ok else "!"}</i><span>{label}</span><b>{value}</b></li>'
                     for ok, label, value in _seo_checks(data))
    review = data.get("review") or {}
    score = review.get("score")
    notes = "".join(f"<li>{html.escape(n)}</li>" for n in (review.get("notes") or [])[:6])
    review_card = (
        '<section class="card"><h2>Editor review<small>AI senior editor</small></h2>'
        f'<div class="score{" lo" if (score or 0) < 8 else ""}">{score}<small>/ 10</small></div>'
        + (f'<ol class="notes">{notes}</ol>' if notes else '<p class="notes">No open points.</p>')
        + '</section>') if score is not None else ""
    tags = "".join(f"<span>{html.escape(t)}</span>" for t in data.get("tags") or [])
    p = client.brand.palette
    # JSON inside <script> must not contain "</" (it would close the tag early).
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    hero = f'<img class="hero" src="{data["image"]}" alt="{html.escape(data["title"])}">' if data["image"] else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(data["title"])}</title>
<meta name="description" content="{html.escape(data["meta_description"])}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>:root{{--deep:{p.get("deep", "#0f172a")};--primary:{p.get("primary", "#014ca9")};--accent:{p.get("accent", "#facc15")}}}
{_PREVIEW_CSS}</style></head><body>
<header class="tb">
  <a class="back" href="/" id="back" hidden>&larr; Dashboard</a><span class="sep" id="back-sep" hidden></span>
  <span class="lbl">Article preview</span>
  <span class="tt">{html.escape(data["title"])}</span>
  <div class="acts">
    <button class="b" type="button" id="toggle" aria-expanded="true" aria-controls="adm">Hide details</button>
    <button class="b pri cp-main" type="button" data-k="content">Copy content HTML</button>
  </div>
</header>
<section class="adm" id="adm" aria-label="Blog fields for the {html.escape(client.brand.name)} admin">
  <div class="adm-in">
    <section class="card"><h2>Blog fields<small>Copy into the {html.escape(client.brand.name)} admin</small></h2>
      {rows}{cover}
    </section>
    <div class="side">
      <section class="card"><h2>SEO check</h2><ul class="chk">{checks}</ul>
        {f'<div class="tags">{tags}</div>' if tags else ""}</section>
      {review_card}
    </div>
  </div>
</section>
<article class="wrap">
<div class="cat">{html.escape(data["category"])}</div>
<h1 class="t">{html.escape(data["title"])}</h1>
<div class="info"><span>{data["date"]}</span><span>{data["readTime"]}</span></div>
{hero}
<div class="c">{data["content"]}</div>
</article>
<script id="data" type="application/json">{payload}</script>
<script>
const DATA = JSON.parse(document.getElementById("data").textContent);
if (location.protocol.startsWith("http")) {{ document.getElementById("back").hidden = false; document.getElementById("back-sep").hidden = false; }}
document.querySelectorAll("button[data-k]").forEach(b => b.onclick = async () => {{
  const text = String(DATA[b.dataset.k] ?? "");
  try {{ await navigator.clipboard.writeText(text); }}
  catch (e) {{ const t = document.createElement("textarea"); t.value = text; document.body.appendChild(t);
               t.select(); document.execCommand("copy"); t.remove(); }}
  const old = b.textContent; b.textContent = "Copied"; b.classList.add("done");
  setTimeout(() => {{ b.textContent = old; b.classList.remove("done"); }}, 1200);
}});
const adm = document.getElementById("adm"), tg = document.getElementById("toggle");
tg.onclick = () => {{ adm.hidden = !adm.hidden; tg.setAttribute("aria-expanded", String(!adm.hidden));
                     tg.textContent = adm.hidden ? "Show details" : "Hide details"; }};
</script></body></html>"""


def save_article(client, data: dict):
    """Write <stamp>-<slug>.json (export) and .html (preview) to data/<client>/drafts/. Returns the .html path."""
    out = client.drafts_dir
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now().strftime('%Y%m%d-%H%M')}-{data['slug'][:60].strip('-')}"
    (out / f"{stem}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    path = out / f"{stem}.html"
    path.write_text(preview_page(client, data), encoding="utf-8")
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
