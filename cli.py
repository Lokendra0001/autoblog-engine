#!/usr/bin/env python3
"""SEO Content Agent — command line.

Usage:
  python cli.py list                         List all clients (and enabled state)
  python cli.py validate <client>            Check config, WP auth, sitemap
  python cli.py run <client> [--dry-run] [--keyword "..."]
  python cli.py run-all [--dry-run]          Run every enabled client
  python cli.py add-client <id>              Scaffold a new client from the template
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
            os.environ.setdefault(k.strip(), v.strip())

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

    for label, val in (("wordpress.site_url", c.wordpress.site_url),
                       ("wordpress.username", c.wordpress.username),
                       ("wordpress.app_password", c.wordpress.app_password)):
        if not val:
            print(f"  [FAIL] missing {label}")
            ok = False

    if c.logo_path:
        print(f"  [OK]   logo found: {c.logo_path.name}")
    else:
        print("  [WARN] no logo file (images will publish unbranded)")

    if c.wordpress.app_password:
        try:
            r = requests.get(f"{c.wordpress.site_url}/wp-json/wp/v2/users/me",
                             auth=(c.wordpress.username, c.wordpress.app_password), timeout=15)
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


def cmd_add_client(args):
    dest = config.CLIENTS_DIR / args.id
    if dest.exists():
        print(f"Client '{args.id}' already exists at {dest}")
        sys.exit(1)
    shutil.copytree(config.CLIENTS_DIR / "_template", dest)
    (dest / "assets").mkdir(exist_ok=True)
    print(f"Created {dest / 'config.yaml'}")
    print("Next: edit it, drop assets/logo.png, then run:")
    print(f"  python cli.py validate {args.id}")
    print(f"  python cli.py run {args.id} --dry-run")


def main():
    p = argparse.ArgumentParser(prog="cli.py", description="SEO Content Agent")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list").set_defaults(func=cmd_list)

    v = sub.add_parser("validate"); v.add_argument("client"); v.set_defaults(func=cmd_validate)

    r = sub.add_parser("run")
    r.add_argument("client"); r.add_argument("--keyword"); r.add_argument("--dry-run", action="store_true")
    r.set_defaults(func=cmd_run)

    ra = sub.add_parser("run-all"); ra.add_argument("--dry-run", action="store_true")
    ra.set_defaults(func=cmd_run_all)

    a = sub.add_parser("add-client"); a.add_argument("id"); a.set_defaults(func=cmd_add_client)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
