#!/usr/bin/env python3
"""AutoBlog Engine — command line.

Usage:
  python cli.py list                         List all clients (and enabled state)
  python cli.py validate <client>            Check API keys, Strapi token, existing blogs
  python cli.py run <client> [--dry-run] [--keyword "..."]
  python cli.py run-all [--dry-run]          Run every enabled client
  python cli.py add-client <id>              Scaffold a new client from the template
  python cli.py serve <client> [--port 8000] Local web page to generate & view articles
  python cli.py plan <client> [--new]        Show (or create) this month's content plan
  python cli.py auto                         Daily job: plan the month + write & upload due articles
  python cli.py push <client> <draft-name>   Upload a saved article to Strapi (skips if already there)
  python cli.py schedule on|off|status       Run `auto` daily at SCHEDULE_TIME (launchd on macOS, cron on Linux)
  python cli.py notify-test                  Send a test notification email
  python cli.py daemon                       Built-in daily scheduler (for Docker; no cron needed)
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

# Load shared platform secrets from .env if present.
_ENV = Path(__file__).resolve().parent / ".env"
if _ENV.exists():
    for line in _ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":  # KEY="value with spaces"
                v = v[1:-1]
            os.environ.setdefault(k.strip(), v)

from agent import config, pipeline, runner  # noqa: E402


def cmd_list(_):
    ids = config.list_clients()
    if not ids:
        print("No clients yet. Create one with: python cli.py add-client <id>")
        return
    for cid in ids:
        c = config.load_client(cid)
        flag = "ENABLED " if c.enabled else "disabled"
        print(f"  [{flag}] {cid:<16} {c.brand.name}  ({c.topic_mode}, {c.posts_per_day}/day)")


def cmd_validate(args):
    import requests
    c = config.load_client(args.client)
    print(f"Validating '{c.id}' ({c.brand.name})")
    ok = True

    if os.getenv("GEMINI_API_KEY"):
        print("  [OK]   GEMINI_API_KEY set")
    else:
        print("  [FAIL] GEMINI_API_KEY missing in .env (articles cannot be written)")
        ok = False
    print("  [OK]   UNSPLASH_ACCESS_KEY set" if os.getenv("UNSPLASH_ACCESS_KEY")
          else "  [WARN] UNSPLASH_ACCESS_KEY missing (articles will have no images)")

    from agent import notify, strapi
    where = {"strapi": "Strapi", "wordpress": "WordPress",
             "files": f"saved only, in data/{c.id}/drafts/ (not published)"}[c.destination]
    print(f"  [OK]   Articles go to: {where}")
    if c.destination == "strapi" and not strapi.enabled(c):
        print("  [FAIL] publish_to is strapi but strapi.url / token is missing")
        ok = False
    if c.destination == "wordpress" and not (c.wordpress.site_url and c.wordpress.app_password):
        print("  [FAIL] publish_to is wordpress but wordpress.site_url / app_password is missing")
        ok = False
    print("  [OK]   Email notifications configured" if notify.configured()
          else "  [WARN] Email notifications off (set RESEND_API_KEY, NOTIFY_FROM, NOTIFY_TO)")
    if c.strapi.url:
        good, msg = strapi.check(c)
        print(f"  [{'OK' if good else 'WARN'}]   Strapi ({c.strapi.url}, upload as {c.strapi.status}): {msg}")
        blogs = strapi.list_blogs(c)
        if blogs is not None:
            print(f"  [OK]   {len(blogs)} blog(s) already on the site (used to avoid duplicates)")

    wp = c.wordpress
    if not wp.site_url:
        pass
    elif not (wp.username and wp.app_password):
        print("  [FAIL] wordpress.site_url is set but username/app_password are missing")
        ok = False
    else:
        try:
            r = requests.get(f"{wp.site_url}/wp-json/wp/v2/users/me",
                             auth=(wp.username, wp.app_password), timeout=15)
            print(f"  [{'OK' if r.status_code == 200 else 'FAIL'}]   WP auth: HTTP {r.status_code}")
            ok = ok and r.status_code == 200
        except Exception as e:
            print(f"  [FAIL] WP auth error: {e}")
            ok = False

    if c.sitemap_url:
        try:
            r = requests.get(c.sitemap_url, timeout=12, verify=False)
            print(f"  [{'OK' if r.status_code == 200 else 'WARN'}]   sitemap: HTTP {r.status_code}")
        except Exception as e:
            print(f"  [WARN] sitemap error: {e}")

    print("RESULT:", "READY" if ok else "NOT READY — fix the FAIL items above")
    sys.exit(0 if ok else 1)


def cmd_run(args):
    c = config.load_client(args.client)
    pipeline.run_once(c, keyword=args.keyword, dry_run=args.dry_run)


def cmd_run_all(args):
    runner.run_all(dry_run=args.dry_run)


def cmd_plan(args):
    from agent import planner
    c = config.load_client(args.client)
    month = planner.local_today(c).strftime("%Y-%m")
    plan = None if args.new else planner.load_plan(c, month)
    plan = plan or planner.create_plan(c)
    if not args.new:
        print(f"Plan for {plan['month']} ({c.brand.name}):")
        for it in plan["items"]:
            print(f"  {it['date']}  {it['status']:<8} [{it['category']}] {it['keyword']}")


ROOT = Path(__file__).resolve().parent
LOG = ROOT / "data" / "auto.log"
# Daily run time, in the business's timezone (the server's own clock may be UTC).
SCHEDULE_TIME = os.getenv("SCHEDULE_TIME", "09:07")
SCHEDULE_TZ = os.getenv("SCHEDULE_TZ", "Asia/Kolkata")


def _trim_log(max_bytes=5_000_000, keep=1_000_000):
    if LOG.exists() and LOG.stat().st_size > max_bytes:
        data = LOG.read_bytes()[-keep:]
        LOG.write_bytes(data[data.find(b"\n") + 1:])


def cmd_auto(_):
    """Daily job for every enabled client. One run at a time (a second one exits immediately)."""
    import fcntl
    import traceback
    from datetime import datetime
    from agent import notify, planner
    LOG.parent.mkdir(exist_ok=True)
    _trim_log()
    lock = open(ROOT / "data" / ".auto.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("[AUTO] Another run is in progress; exiting.")
        return
    print(f"\n===== auto run {datetime.now().isoformat(timespec='seconds')} =====")
    for cid in config.list_clients(enabled_only=True):
        try:
            planner.run_due(config.load_client(cid))
        except Exception:
            err = traceback.format_exc()
            print(f"[ERROR] [{cid}] auto run failed:\n{err}")
            notify.crash(f"client '{cid}'", err)


def _local_run_time():
    """SCHEDULE_TIME in SCHEDULE_TZ, converted to this machine's local clock -> (hour, minute)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    h, m = map(int, SCHEDULE_TIME.split(":"))
    there = datetime.now(ZoneInfo(SCHEDULE_TZ)).replace(hour=h, minute=m, second=0, microsecond=0)
    here = there.astimezone()
    return here.hour, here.minute


def _python():
    venv = ROOT / "venv" / "bin" / "python"
    return str(venv if venv.exists() else Path(sys.executable))


_LABEL = "com.seowriter.auto"
_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{_LABEL}.plist"
_CRON_TAG = "# seowriter-auto"


def _schedule_macos(action, hour, minute):
    import plistlib
    import subprocess
    if action == "on":
        _PLIST.parent.mkdir(parents=True, exist_ok=True)
        _PLIST.write_bytes(plistlib.dumps({
            "Label": _LABEL, "ProgramArguments": [_python(), str(ROOT / "cli.py"), "auto"],
            "WorkingDirectory": str(ROOT),
            # If the Mac is asleep at this time, launchd runs the job when it wakes.
            "StartCalendarInterval": {"Hour": hour, "Minute": minute},
            "StandardOutPath": str(LOG), "StandardErrorPath": str(LOG)}))
        subprocess.run(["launchctl", "unload", str(_PLIST)], capture_output=True)
        subprocess.run(["launchctl", "load", str(_PLIST)], check=True)
    elif action == "off" and _PLIST.exists():
        subprocess.run(["launchctl", "unload", str(_PLIST)], capture_output=True)
        _PLIST.unlink()
    return subprocess.run(["launchctl", "list", _LABEL], capture_output=True).returncode == 0


def _schedule_cron(action, hour, minute):
    import shlex
    import subprocess
    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    lines = [l for l in (current.stdout if current.returncode == 0 else "").splitlines() if _CRON_TAG not in l]
    if action == "on":
        lines.append(f"{minute} {hour} * * * cd {shlex.quote(str(ROOT))} && {shlex.quote(_python())} cli.py auto "
                     f">> {shlex.quote(str(LOG))} 2>&1 {_CRON_TAG}")
    if action in ("on", "off"):
        subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True)
        current = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return _CRON_TAG in current.stdout


def cmd_schedule(args):
    """Run `auto` daily at SCHEDULE_TIME (SCHEDULE_TZ): launchd on macOS, cron on Linux."""
    LOG.parent.mkdir(exist_ok=True)
    hour, minute = _local_run_time()
    on = (_schedule_macos if sys.platform == "darwin" else _schedule_cron)(args.action, hour, minute)
    when = f"daily at {SCHEDULE_TIME} {SCHEDULE_TZ} (= {hour:02d}:{minute:02d} on this machine's clock)"
    print(f"Schedule: {'ON, ' + when if on else 'OFF'}" + (f". Log: {LOG}" if on else ""))


def cmd_notify_test(_):
    """Send a test email to check the RESEND_API_KEY / NOTIFY_FROM / NOTIFY_TO settings."""
    from agent import notify
    if not notify.configured():
        sys.exit("Set RESEND_API_KEY, NOTIFY_FROM and NOTIFY_TO in .env first.")
    ok = notify.send("[AutoBlog Engine] Test email",
                     "<p>Notifications are working. You will get an email when an article is drafted or "
                     "published, when the monthly plan is created, and whenever something needs attention.</p>")
    sys.exit(0 if ok else 1)


def cmd_push(args):
    """Upload a saved article (data/<client>/drafts/<name>) to Strapi or WordPress."""
    c = config.load_client(args.client)
    if c.destination == "files":
        sys.exit("No destination: set up Strapi or WordPress in config.yaml (and publish_to / PUBLISH_TO)")
    drafts = c.drafts_dir
    matches = sorted(drafts.glob(f"*{args.name}*.json"))
    if len(matches) != 1:
        sys.exit(f"Expected one draft matching '{args.name}', found {len(matches)}: "
                 + ", ".join(m.stem for m in matches[:10]))
    print(pipeline.upload_saved(c, matches[0].with_suffix(".html")))


def cmd_serve(args):
    from agent import web
    web.serve(config.load_client(args.client), port=args.port, host=args.host)


HEARTBEAT = ROOT / "data" / ".heartbeat"


def cmd_daemon(_):
    """Long-running scheduler (used in Docker): runs `auto` daily at SCHEDULE_TIME in SCHEDULE_TZ.
    No cron needed. Set RUN_ON_START=1 to also run once at startup (missed days catch up anyway)."""
    import time
    import traceback
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(SCHEDULE_TZ)
    h, m = map(int, SCHEDULE_TIME.split(":"))
    HEARTBEAT.parent.mkdir(exist_ok=True)
    print(f"[DAEMON] Started. Daily run at {SCHEDULE_TIME} {SCHEDULE_TZ}.", flush=True)
    names = "Mon Tue Wed Thu Fri Sat Sun".split()
    for cid in config.list_clients(enabled_only=True):
        c = config.load_client(cid)  # fails fast here if POSTS_PER_MONTH / PUBLISH_DAYS are invalid
        print(f"[DAEMON] {cid}: {c.posts_per_month} posts/month on "
              f"{', '.join(names[d] for d in c.publish_weekdays)}", flush=True)

    def run():
        try:
            cmd_auto(None)
        except Exception:
            print(f"[DAEMON] Run failed:\n{traceback.format_exc()}", flush=True)

    if os.getenv("RUN_ON_START") == "1":
        run()
    while True:
        now = datetime.now(tz)
        nxt = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        print(f"[DAEMON] Next run: {nxt.strftime('%a %d %b %Y %H:%M %Z')}", flush=True)
        while (left := (nxt - datetime.now(tz)).total_seconds()) > 0:
            HEARTBEAT.write_text(datetime.now(tz).isoformat(timespec="seconds"))
            time.sleep(min(left, 60))  # short sleeps: robust to clock changes and container pauses
        run()


def cmd_add_client(args):
    dest = config.CLIENTS_DIR / args.id
    if dest.exists():
        print(f"Client '{args.id}' already exists at {dest}")
        sys.exit(1)
    shutil.copytree(config.CLIENTS_DIR / "_template", dest)
    print(f"Created {dest / 'config.yaml'}")
    print("Next: edit it, then run:")
    print(f"  python cli.py validate {args.id}")
    print(f"  python cli.py run {args.id} --dry-run")


def main():
    p = argparse.ArgumentParser(prog="cli.py", description="AutoBlog Engine")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list").set_defaults(func=cmd_list)

    v = sub.add_parser("validate"); v.add_argument("client"); v.set_defaults(func=cmd_validate)

    r = sub.add_parser("run")
    r.add_argument("client"); r.add_argument("--keyword"); r.add_argument("--dry-run", action="store_true")
    r.set_defaults(func=cmd_run)

    ra = sub.add_parser("run-all"); ra.add_argument("--dry-run", action="store_true")
    ra.set_defaults(func=cmd_run_all)

    pl = sub.add_parser("plan"); pl.add_argument("client"); pl.add_argument("--new", action="store_true")
    pl.set_defaults(func=cmd_plan)

    sub.add_parser("auto").set_defaults(func=cmd_auto)

    sc = sub.add_parser("schedule"); sc.add_argument("action", choices=["on", "off", "status"])
    sc.set_defaults(func=cmd_schedule)

    sub.add_parser("notify-test").set_defaults(func=cmd_notify_test)

    pu = sub.add_parser("push"); pu.add_argument("client"); pu.add_argument("name"); pu.set_defaults(func=cmd_push)

    sub.add_parser("daemon").set_defaults(func=cmd_daemon)

    sv = sub.add_parser("serve"); sv.add_argument("client"); sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--host", default="127.0.0.1", help="0.0.0.0 inside Docker")
    sv.set_defaults(func=cmd_serve)

    a = sub.add_parser("add-client"); a.add_argument("id"); a.set_defaults(func=cmd_add_client)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
