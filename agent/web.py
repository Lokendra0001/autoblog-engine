"""Local test page: type a keyword, generate an article, view it. No publishing.

Binds to 127.0.0.1 only, so it is reachable from this computer alone.
"""

from __future__ import annotations

import html
import threading
import uuid
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote

from . import pipeline, planner, strapi

_JOB_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta http-equiv="refresh" content="5">
<title>Writing article…</title>
<style>body{{max-width:640px;margin:80px auto;padding:0 16px;font-family:system-ui,sans-serif;color:#222}}
.hint{{color:#666}}</style></head><body>
<h1>Writing: {keyword}</h1>
<p>Researching, writing and reviewing the article (up to 3 drafts). This usually takes 1–4 minutes.</p>
<p class="hint">Started {started}. This page refreshes itself; you can also close it and find the
article under "Recent articles" later.</p>
</body></html>"""

_FORM = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AutoBlog Engine</title>
<style>
body{{max-width:640px;margin:60px auto;padding:0 16px;font-family:system-ui,sans-serif;color:#222;background:#fff}}
input{{width:100%;padding:12px;font-size:16px;border:1px solid #ccc;border-radius:8px;box-sizing:border-box}}
button{{margin-top:12px;padding:12px 20px;font-size:16px;border:0;border-radius:8px;background:#222;color:#fff;cursor:pointer}}
button:disabled{{background:#888;cursor:wait}}
.err{{color:#b00020}} .hint{{color:#666;font-size:14px}}
li{{margin:6px 0}}
table{{width:100%;border-collapse:collapse;font-size:14px;margin-bottom:24px}}
td,th{{border-bottom:1px solid #eee;padding:8px 6px;text-align:left;vertical-align:top}}
.s-done{{color:#0a7a3d}} .s-failed{{color:#b00020}} .s-planned,.s-skipped{{color:#666}}
label.cb{{display:block;margin-top:12px;font-size:15px}} label.cb input{{width:auto}}
</style></head><body>
<h1>AutoBlog Engine</h1>
<p class="hint">Client: <b>{client}</b>. Each article is saved as a preview page plus a JSON export.</p>
{error}
{plan}
<h2>Write an article now</h2>
<form method="post" action="/generate" onsubmit="b.disabled=true">
<label for="k">Keyword or topic</label>
<input id="k" name="keyword" required placeholder="e.g. {example}" autofocus>
{upload_box}
<button id="b" type="submit">Generate article</button>
</form>
{drafts}
</body></html>"""


def serve(client, port=8000, host="127.0.0.1"):
    drafts_dir = client.drafts_dir
    jobs: dict[str, dict] = {}
    lock = threading.Lock()

    def run_job(job_id, keyword, upload):
        try:
            path = pipeline.preview_article(client, keyword, upload=upload)["path"]
            update = {"status": "done", "draft": path.name}
        except Exception as e:
            print(f"[ERROR] {e}")
            update = {"status": "failed", "error": str(e)}
        with lock:
            jobs[job_id].update(update)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="text/html; charset=utf-8", headers=None):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _form(self, error=""):
            files = sorted(drafts_dir.glob("*.html"), reverse=True)[:10] if drafts_dir.exists() else []
            drafts = ("<h2>Recent articles</h2><ul>" + "".join(
                f'<li><a href="/drafts/{quote(f.name)}">{html.escape(f.stem)}</a></li>' for f in files)
                + "</ul>") if files else ""
            err = f'<p class="err">{html.escape(error)}</p>' if error else ""
            status = client.strapi.status if client.destination == "strapi" else client.wordpress.status
            upload_box = (f'<label class="cb"><input type="checkbox" name="upload" value="1"> Also upload to the '
                          f'website ({client.destination.title()}, as {html.escape(status)})</label>'
                          if client.destination != "files" else "")
            self._send(200, _FORM.format(client=html.escape(client.brand.name), error=err, upload_box=upload_box,
                                         example=html.escape((client.sources.keyword_seeds or ['your main topic'])[0]),
                                         plan=self._plan_html(), drafts=drafts))

        def _plan_html(self):
            plan = planner.load_plan(client, planner.local_today(client).strftime("%Y-%m"))
            if not plan or not plan["items"]:
                return "<p class='hint'>No plan for this month yet. It is created automatically.</p>"
            rows = ""
            for it in plan["items"]:
                name = html.escape(it["title"] or it["keyword"])
                if it.get("draft"):
                    name = f'<a href="/drafts/{quote(it["draft"])}">{name}</a>'
                status = it["status"] + (f'<br><span class="hint">website: {it["upload"]}</span>' if it.get("upload") else "")
                note = it.get("last_error", "") if it["status"] in ("skipped", "failed") else ""
                rows += (f'<tr><td>{it["date"]}</td><td class="s-{it["status"]}">{status}</td>'
                         f'<td>{name}<br><span class="hint">{html.escape(it["category"])} {html.escape(note)}</span></td></tr>')
            return (f"<h2>Plan for {plan['month']}</h2><table><tr><th>Date</th><th>Status</th>"
                    f"<th>Article</th></tr>{rows}</table>")

        def do_GET(self):
            if self.path == "/":
                return self._form()
            if self.path.startswith("/drafts/"):
                name = unquote(self.path[len("/drafts/"):])
                f = drafts_dir / name
                # Only plain filenames inside the drafts folder — no path traversal.
                types = {".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8",
                         ".jpg": "image/jpeg"}
                if "/" not in name and "\\" not in name and f.suffix in types and f.is_file():
                    return self._send(200, f.read_bytes(), types[f.suffix])
            if self.path.startswith("/jobs/"):
                with lock:
                    job = dict(jobs.get(self.path[len("/jobs/"):], {}))
                if job.get("status") == "done":
                    return self._send(303, "", headers={"Location": f"/drafts/{quote(job['draft'])}"})
                if job.get("status") == "failed":
                    return self._form(f"Generation failed for \"{job['keyword']}\": {job['error']}")
                if job:
                    return self._send(200, _JOB_PAGE.format(keyword=html.escape(job["keyword"]),
                                                            started=job["started"]))
            self._send(404, "Not found", "text/plain; charset=utf-8")

        def do_POST(self):
            if self.path != "/generate":
                return self._send(404, "Not found", "text/plain; charset=utf-8")
            length = min(int(self.headers.get("Content-Length") or 0), 10_000)
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            keyword = form.get("keyword", [""])[0].strip()[:200]
            upload = form.get("upload", [""])[0] == "1"
            if not keyword:
                return self._form("Please enter a keyword.")
            hit = strapi.find_existing(strapi.list_blogs(client) or [], keyword=keyword)
            if hit:  # checked here too, so the page answers at once instead of starting a job
                return self._form(f'Not written: "{hit["title"]}" is already on the website ({hit["status"]}).')
            with lock:  # one article at a time: protects the daily free AI quota
                running = next((i for i, j in jobs.items() if j["status"] == "running"), None)
                if running is None:
                    running = uuid.uuid4().hex[:12]
                    jobs[running] = {"status": "running", "keyword": keyword,
                                     "started": datetime.now().strftime("%H:%M:%S")}
                    threading.Thread(target=run_job, args=(running, keyword, upload), daemon=True).start()
            self._send(303, "", headers={"Location": f"/jobs/{running}"})

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"[WEB] Listening on {host}:{port}. Open http://127.0.0.1:{port} in your browser (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[WEB] Stopped")
