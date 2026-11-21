"""Email notifications (Resend) so an unattended server never fails silently.

Configured with environment variables (.env):
  RESEND_API_KEY  – Resend API key
  NOTIFY_FROM     – sender on a domain verified in Resend, e.g. "Blog Bot <blog@yourdomain.com>"
  NOTIFY_TO       – recipient(s), comma-separated
Without them, notifications are skipped (and the reason is logged). Sending never raises.
"""

from __future__ import annotations

import html
import os

import requests


def configured() -> bool:
    return all(os.getenv(k) for k in ("RESEND_API_KEY", "NOTIFY_FROM", "NOTIFY_TO"))


def send(subject: str, body_html: str) -> bool:
    if not configured():
        print(f"[NOTIFY] Email not configured, skipped: {subject}")
        return False
    try:
        r = requests.post("https://api.resend.com/emails", timeout=20,
                          headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
                          json={"from": os.environ["NOTIFY_FROM"],
                                "to": [a.strip() for a in os.environ["NOTIFY_TO"].split(",") if a.strip()],
                                "subject": subject, "html": body_html})
        if r.status_code >= 400:
            print(f"[NOTIFY] Email failed: HTTP {r.status_code} {r.text[:200]}")
            return False
        print(f"[NOTIFY] Email sent: {subject}")
        return True
    except Exception as e:
        print(f"[NOTIFY] Email failed: {e}")
        return False


# ── templates ────────────────────────────────────────────────────────────────

def _layout(client, heading: str, inner: str) -> str:
    p = client.brand.palette
    return f"""<div style="font-family:Arial,Helvetica,sans-serif;max-width:640px;margin:0 auto;color:#1f2937">
<div style="background:{p.get('primary', '#014ca9')};color:#fff;padding:18px 24px;border-radius:10px 10px 0 0">
<div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;opacity:.85">{html.escape(client.brand.name)} · Blog automation</div>
<div style="font-size:20px;font-weight:700;margin-top:4px">{html.escape(heading)}</div></div>
<div style="border:1px solid #e5e7eb;border-top:0;padding:20px 24px;border-radius:0 0 10px 10px;font-size:14px;line-height:1.6">
{inner}</div>
<p style="font-size:12px;color:#9ca3af;margin-top:12px">Sent automatically by AutoBlog Engine. Plan and drafts: data/{html.escape(client.id)}/</p></div>"""


def _button(url: str, label: str) -> str:
    return (f'<p><a href="{html.escape(url)}" style="display:inline-block;background:#0f172a;color:#fff;'
            f'padding:10px 18px;border-radius:6px;text-decoration:none;font-weight:600">{html.escape(label)}</a></p>')


def _row(label: str, value: str) -> str:
    return (f'<tr><td style="padding:4px 12px 4px 0;color:#6b7280;white-space:nowrap">{html.escape(label)}</td>'
            f'<td style="padding:4px 0">{value}</td></tr>')


_CMS = {"strapi": "Strapi", "wordpress": "WordPress", "files": "files"}


def admin_url(client, document_id: str) -> str:
    """Edit link for an uploaded article in the CMS admin."""
    if client.destination == "wordpress":
        return f"{client.wordpress.site_url.rstrip('/')}/wp-admin/post.php?post={document_id}&action=edit"
    coll = client.strapi.collection
    single = coll[:-1] if coll.endswith("s") else coll  # Strapi UID: api::<singular>.<singular>
    return (f"{client.strapi.url.rstrip('/')}/admin/content-manager/collection-types/"
            f"api::{single}.{single}/{document_id}")


def run_report(client, events: list[dict]) -> None:
    """One email per daily run summarising what happened. Subject reflects the most important event."""
    if not events:
        return
    kinds = {e["kind"] for e in events}
    if "failed" in kinds or "upload_failed" in kinds:
        subject = "Action needed: blog article problem"
    elif "published" in kinds:
        subject = "Published: " + next(e["title"] for e in events if e["kind"] == "published")
    elif "draft" in kinds:
        subject = "Draft ready for review: " + next(e["title"] for e in events if e["kind"] == "draft")
    elif "saved" in kinds:
        subject = "New article ready: " + next(e["title"] for e in events if e["kind"] == "saved")
    elif "retry" in kinds:
        subject = "Blog article delayed, will retry tomorrow"
    else:
        subject = "Blog automation update"

    cms = _CMS[client.destination]
    blocks = []
    for e in events:
        k = e["kind"]
        if k in ("draft", "published", "saved"):
            score = e.get("score")
            notes = "".join(f"<li>{html.escape(n[:220])}</li>" for n in (e.get("notes") or [])[:4])
            rows = (_row("Title", f"<b>{html.escape(e['title'])}</b>") + _row("Keyword", html.escape(e["keyword"]))
                    + _row("Category", html.escape(e.get("category", ""))) + _row("Length", html.escape(e.get("read_time", "")))
                    + (_row("Editor score", f"{score}/10") if score else ""))
            if k == "published":
                action = _button(e["url"], "View the live post")
            elif k == "draft":
                action = (f"<p>The article is saved as a <b>draft</b> in {cms}. Review it, then click <b>Publish</b>.</p>"
                          + _button(admin_url(client, e["document_id"]), f"Review in {cms}"))
            else:
                action = (f"<p>Saved on the server (not published): <code>data/{html.escape(client.id)}/drafts/"
                          f"{html.escape(e.get('file', ''))}</code> with its .json export and cover image.</p>")
            heading = {"published": "Published", "draft": "New draft", "saved": "New article"}[k]
            blocks.append(f"<h3 style='margin:0 0 8px'>{heading}</h3>"
                          f"<table style='font-size:14px'>{rows}</table>{action}"
                          + (f"<p style='color:#6b7280;margin-bottom:4px'>Editor notes worth a look:</p><ul>{notes}</ul>"
                             if notes and k != "published" else ""))
        elif k == "exists":
            blocks.append(f"<p><b>Not uploaded:</b> {html.escape(e['title'])} — the same topic is already on the site "
                          f"(“{html.escape(e['existing'])}”).</p>")
        elif k == "skipped":
            blocks.append(f"<p><b>Skipped:</b> “{html.escape(e['keyword'])}” — {html.escape(e['reason'])}</p>")
        elif k == "retry":
            blocks.append(f"<p><b>Delayed:</b> “{html.escape(e['keyword'])}” could not be written today "
                          f"(attempt {e['attempt']} of {e['max']}). It will be retried on the next daily run.<br>"
                          f"<span style='color:#6b7280'>{html.escape(e['error'][:300])}</span></p>")
        elif k == "failed":
            blocks.append(f"<p style='color:#b00020'><b>Failed:</b> “{html.escape(e['keyword'])}” after "
                          f"{e['max']} attempts. It will not be retried automatically.<br>"
                          f"<span style='color:#6b7280'>{html.escape(e['error'][:300])}</span></p>")
        elif k == "upload_failed":
            blocks.append(f"<p style='color:#b00020'><b>Upload failed:</b> {html.escape(e['title'])} was written but "
                          f"could not be uploaded to {cms}. It is retried on the next daily run.<br>"
                          f"<span style='color:#6b7280'>{html.escape(e['error'][:300])}</span></p>")
        elif k == "plan":
            items = "".join(f"<li>{html.escape(i['date'])} · <b>{html.escape(i['keyword'])}</b> "
                            f"<span style='color:#6b7280'>({html.escape(i['category'])})</span></li>" for i in e["items"])
            blocks.append(f"<h3 style='margin:0 0 8px'>Content plan for {html.escape(e['month'])}</h3><ul>{items}</ul>")
    send(f"[{client.brand.name}] {subject}",
         _layout(client, subject, "<hr style='border:0;border-top:1px solid #e5e7eb;margin:16px 0'>".join(blocks)))


def crash(where: str, error_text: str) -> None:
    """The daily job itself crashed (bug, server problem)."""
    send("[AutoBlog Engine] Daily blog job crashed",
         f"<div style='font-family:Arial,sans-serif'><p>The daily blog job failed in <b>{html.escape(where)}</b>. "
         f"No article was lost; the job runs again tomorrow.</p><pre style='background:#f3f4f6;padding:12px;"
         f"border-radius:6px;white-space:pre-wrap;font-size:12px'>{html.escape(error_text[-3000:])}</pre></div>")
