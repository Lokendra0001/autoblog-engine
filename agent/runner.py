"""Multi-tenant runner: iterate enabled clients and run their pipeline.

This is what a single cron/scheduled invocation calls to service every client.
"""

from __future__ import annotations

from . import config, pipeline


def run_all(dry_run=False):
    ids = config.list_clients(enabled_only=True)
    if not ids:
        print("[INFO] No enabled clients found.")
        return
    print(f"[RUNNER] Servicing {len(ids)} enabled client(s): {', '.join(ids)}")
    results = {}
    for cid in ids:
        client = config.load_client(cid)
        for n in range(max(1, client.posts_per_day)):
            try:
                print(f"\n=== {cid} — post {n + 1}/{client.posts_per_day} ===")
                results.setdefault(cid, []).append(pipeline.run_once(client, dry_run=dry_run))
            except Exception as e:
                print(f"[ERROR] [{cid}] run failed: {e}")
                results.setdefault(cid, []).append({"error": str(e)})
    return results
