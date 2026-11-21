"""Monthly content planner + scheduled writer (fully automatic, no human step).

Each month gets a plan file data/<client>/plans/YYYY-MM.json listing dated topics.
`run_due` is what the daily scheduler calls: it creates the month's plan if missing,
then writes every planned article whose date has arrived (so missed days catch up) and
uploads it to Strapi. Topics already on the website are never planned, written or uploaded.
"""

from __future__ import annotations

import calendar
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import keywords, notify, pipeline, trends
from .ai import call_ai
from .state import ClientState

MAX_ATTEMPTS = 3
NEWS_DAYS = 7  # how far back the publish-day news check looks


def _plan_path(client, month: str):
    d = client.data_dir / "plans"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{month}.json"


def load_plan(client, month: str):
    p = _plan_path(client, month)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def save_plan(client, plan):
    _plan_path(client, plan["month"]).write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")


def _schedule_dates(client, today: date) -> list[date]:
    """Publish dates for the rest of this month, spread evenly over the allowed weekdays.

    A plan created mid-month gets a pro-rated number of articles.
    """
    days = calendar.monthrange(today.year, today.month)[1]
    all_dates = [date(today.year, today.month, d) for d in range(1, days + 1)
                 if date(today.year, today.month, d).weekday() in client.publish_weekdays]
    remaining = [d for d in all_dates if d >= today]
    if not remaining:
        return []
    n = max(1, round(client.posts_per_month * len(remaining) / len(all_dates)))
    n = min(n, len(remaining))
    step = len(remaining) / n
    return [remaining[int(step * i + step / 2)] for i in range(n)]


def local_today(client) -> date:
    """Today's date in the client's timezone (servers usually run on UTC)."""
    return datetime.now(ZoneInfo(client.timezone)).date()


def create_plan(client, today: date | None = None):
    today = today or local_today(client)
    month = today.strftime("%Y-%m")
    dates = _schedule_dates(client, today)
    if not dates:
        print(f"[PLAN] No publish dates left in {month}.")
        plan = {"month": month, "created": datetime.now().isoformat(timespec="seconds"), "items": []}
        save_plan(client, plan)
        return plan

    print(f"[PLAN] [{client.id}] Planning {len(dates)} article(s) for {month}...")
    headlines = trends.gather_headlines(client)
    searches = keywords.expand(client.sources.keyword_seeds, client) if client.sources.keyword_seeds else []
    print(f"[PLAN] {len(headlines)} headlines, {len(searches)} real Google searches")
    # Never plan a topic that is already a blog on the website or was written before.
    used = list(dict.fromkeys(pipeline.site_titles(client) + trends.used_topic_list(ClientState(client), limit=100)))

    exclude = "".join(f", {x}" for x in client.sources.keyword_exclude)

    prompt = f"""You are the head of content for {client.brand.name}. Plan the blog for {month}.

ABOUT THE COMPANY:
{client.context or client.brand.name}

READERS: {client.audience} in {client.geo_label}
CATEGORIES: {", ".join(client.categories)}

REAL GOOGLE SEARCHES in {client.geo_label} (what these readers actually type). Prefer these, or close
natural variants, as focus keywords. Skip searches about other countries, competitor names and other
companies' listings{exclude}:
{chr(10).join(searches[:120]) or "None available."}

RECENT INDUSTRY HEADLINES (use for timely angles where relevant):
{chr(10).join(headlines[:40]) or "None available."}

ALREADY PUBLISHED (never repeat or closely imitate):
{chr(10).join(used) if used else "None yet."}

Plan exactly {len(dates) + 3} articles (a few spares). Requirements:
- A balanced mix across categories; no two articles on the same sub-topic.
- Each targets a specific keyword from the real searches above where possible (high intent, realistic
  to rank). Include at most one commercial keyword (e.g. price or supplier) per month.
- Mostly evergreen, expert topics; at most one news-driven article, only if a headline is relevant.
- Professional, decision-useful angles that let {client.brand.name} show real expertise.

Return a JSON array of {len(dates) + 3} objects with keys:
"keyword" (2-6 word focus keyword, at most 45 characters, starting with the main term), "angle" (1-2 sentence brief: what the article covers and for whom),
"category" (one of the categories above)."""

    raw = call_ai(messages=[{"role": "user", "content": prompt}], max_tokens=3000,
                  tier="smart", json_mode=True)
    ideas = json.loads(raw)
    if isinstance(ideas, dict):  # tolerate {"articles": [...]}
        ideas = next((v for v in ideas.values() if isinstance(v, list)), [])
    # The model sometimes ignores the "already published" list, so filter in code too.
    fresh = []
    for idea in ideas:
        kw = str(idea.get("keyword", "")).strip()
        if kw and not ClientState.is_duplicate(kw, used + [i["keyword"] for i in fresh]):
            fresh.append({"keyword": kw, "angle": str(idea.get("angle", "")).strip(),
                          "category": str(idea.get("category", "")).strip()})
    items = [{"date": d.isoformat(), **idea, "status": "planned", "attempts": 0, "title": None, "draft": None}
             for d, idea in zip(dates, fresh)]

    plan = {"month": month, "created": datetime.now().isoformat(timespec="seconds"), "items": items}
    save_plan(client, plan)
    for it in items:
        print(f"  {it['date']}  [{it['category']}] {it['keyword']}")
    return plan


def _fresh_topic(client, it, used: list[str]) -> dict | None:
    """On the publish day: a topic from the last week's news that deserves the article more than the
    planned one, or None (then the planned topic is written). Never raises."""
    headlines = trends.gather_headlines(client, days=NEWS_DAYS, extra_queries=client.sources.keyword_seeds)
    if not headlines:
        print(f"[NEWS] No news in the last {NEWS_DAYS} days; writing the planned topic.")
        return None
    prompt = f"""You choose today's blog article for {client.brand.name}.

ABOUT THE COMPANY:
{client.context or client.brand.name}

READERS: {client.audience} in {client.geo_label}
CATEGORIES: {", ".join(client.categories)}

PLANNED TOPIC (the default): "{it['keyword']}" ({it.get('category', '')}): {it.get('angle', '')}

NEWS FROM THE LAST {NEWS_DAYS} DAYS:
{chr(10).join(headlines[:60])}

ALREADY PUBLISHED OR PLANNED (never repeat these topics):
{chr(10).join(used[-120:]) or "None yet."}

Is there a news item that is a real, relevant development for these readers (a new project, policy,
standard, study, market change or event related to the company's products or industry in
{client.geo_label}) and gives enough substance for a useful article today? Be strict: generic, unrelated,
promotional, foreign-only or minor news does not count. If nothing qualifies, keep the planned topic.

Return JSON: {{"use_news": true or false, "reason": "one short sentence",
"keyword": "2-6 word focus keyword, at most 45 characters, starting with the main term",
"angle": "1-2 sentence brief, mentioning the news", "category": "one of the categories above"}}
(keyword, angle and category only when use_news is true)."""
    try:
        data = json.loads(call_ai(messages=[{"role": "user", "content": prompt}], max_tokens=600,
                                  tier="fast", json_mode=True))
    except Exception as e:
        print(f"[NEWS] News check failed ({str(e)[:120]}); writing the planned topic.")
        return None
    if not isinstance(data, dict) or not data.get("use_news"):
        print(f"[NEWS] Keeping the planned topic: {(data or {}).get('reason', 'no relevant news')}")
        return None
    kw = str(data.get("keyword", "")).strip()
    if not kw or ClientState.is_duplicate(kw, used):
        print(f"[NEWS] News topic \"{kw}\" is empty or already covered; writing the planned topic.")
        return None
    print(f"[NEWS] Using a fresh news topic: {kw} ({data.get('reason', '')})")
    return {"keyword": kw, "angle": str(data.get("angle", "")).strip(),
            "category": str(data.get("category", "")).strip()}


def _article_event(client, it, result) -> dict | None:
    """Notification event for a written article, based on its upload outcome."""
    data, up = result["data"], result.get("upload")
    base = {"title": data["title"], "keyword": it["keyword"], "category": data["category"],
            "read_time": data["readTime"], "score": data.get("review", {}).get("score"),
            "notes": data.get("review", {}).get("notes", []), "planned_keyword": it.get("planned_keyword", "")}
    if not up:  # destination "files": saved only
        return {**base, "kind": "saved", "file": result["path"].name if result.get("path") else ""}
    if up["result"] == "uploaded":
        kind = "published" if up["status"] == "published" else "draft"
        return {**base, "kind": kind, "url": up.get("url", ""), "document_id": up["documentId"]}
    if up["result"] == "exists":
        return {"kind": "exists", "title": data["title"], "existing": up["title"]}
    return {"kind": "upload_failed", "title": data["title"], "error": up.get("reason", "")}


def run_due(client, today: date | None = None, pull_next: bool = False):
    """Create this month's plan if needed, write every due article and upload it. Safe to run daily.
    Sends one summary email per run when anything happened (see agent/notify.py).
    pull_next=True moves the next planned article to today first (to test the full daily workflow)."""
    today = today or local_today(client)
    month = today.strftime("%Y-%m")
    events: list[dict] = []
    plan = load_plan(client, month)
    if not plan:
        plan = create_plan(client, today)
        if plan["items"]:
            events.append({"kind": "plan", "month": month, "items": plan["items"]})
    if pull_next:
        nxt = next((it for it in plan["items"] if it["status"] == "planned"), None)
        if not nxt:
            print(f"[AUTO] [{client.id}] No planned articles left in {month}.")
        elif nxt["date"] > today.isoformat():
            print(f"[AUTO] [{client.id}] Moving \"{nxt['keyword']}\" from {nxt['date']} to today.")
            nxt["date"] = today.isoformat()
            save_plan(client, plan)
    try:
        _run_plan(client, plan, today, events)
    finally:
        notify.run_report(client, events)


def _run_plan(client, plan, today, events):
    # Uploads that failed earlier (e.g. the CMS was down) are retried first.
    for it in plan["items"]:
        if it["status"] == "done" and it.get("upload") == "failed" and client.destination != "files":
            print(f"[AUTO] [{client.id}] Retrying upload: {it['title']}")
            path = client.drafts_dir / it["draft"]
            up = pipeline.upload_saved(client, path)
            it["upload"] = up["result"]
            save_plan(client, plan)
            data = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
            event = _article_event(client, it, {"data": data, "upload": up})
            if event and event["kind"] != "upload_failed":  # don't repeat the same failure every day
                events.append(event)

    due = [it for it in plan["items"] if it["status"] == "planned" and it["date"] <= today.isoformat()]
    if not due:
        nxt = next((it["date"] for it in plan["items"] if it["status"] == "planned"), None)
        print(f"[AUTO] [{client.id}] Nothing due today." + (f" Next article: {nxt}" if nxt else ""))
        return

    for it in due:
        news_used = sum(1 for x in plan["items"] if x.get("planned_keyword"))
        if news_used < client.max_news_per_month and not it.get("news_checked"):
            used = (pipeline.site_titles(client) + trends.used_topic_list(ClientState(client), limit=100)
                    + [x["keyword"] for x in plan["items"] if x is not it])
            fresh = _fresh_topic(client, it, used)
            if fresh:
                it["planned_keyword"] = it["keyword"]
                it.update(fresh)
            it["news_checked"] = True  # a retry tomorrow writes the same topic
            save_plan(client, plan)
        print(f"\n[AUTO] [{client.id}] Writing: {it['keyword']} (planned for {it['date']})")
        brief = it["angle"]
        if it["category"] in client.categories:
            brief += f" Use the category: {it['category']}."
        try:
            result = pipeline.preview_article(client, it["keyword"], brief=brief, publish_date=it["date"])
            it.update(status="done", title=result["title"], draft=result["path"].name,
                      written=datetime.now().isoformat(timespec="seconds"))
            if "upload" in result:
                it["upload"] = result["upload"]["result"]
            event = _article_event(client, it, result)
            if event:
                events.append(event)
        except pipeline.AlreadyOnSite as e:
            it.update(status="skipped", last_error=str(e))
            events.append({"kind": "skipped", "keyword": it["keyword"], "reason": str(e)})
            print(f"[AUTO] [{client.id}] Skipped: {e}")
        except Exception as e:
            it["attempts"] += 1
            it["last_error"] = str(e)[:300]
            if it["attempts"] >= MAX_ATTEMPTS:
                it["status"] = "failed"
            events.append({"kind": "failed" if it["status"] == "failed" else "retry", "keyword": it["keyword"],
                           "attempt": it["attempts"], "max": MAX_ATTEMPTS, "error": str(e)})
            print(f"[ERROR] [{client.id}] {it['keyword']}: {e} (attempt {it['attempts']}/{MAX_ATTEMPTS})")
        save_plan(client, plan)
