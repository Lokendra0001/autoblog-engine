"""Search-engine indexing: cache flush, Google Indexing API, IndexNow (Bing/Yandex).

Per-client: IndexNow key and the optional Google service-account credentials path
both come from the client config.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import requests


def clear_wp_cache(client):
    auth = (client.wordpress.username, client.wordpress.app_password)
    base = client.wordpress.site_url
    for endpoint in (f"{base}/wp-json/w3tc/v1/flush",
                     f"{base}/wp-json/wp-super-cache/v1/cache",
                     f"{base}/wp-json/litespeed/v1/purge/all"):
        try:
            r = requests.post(endpoint, auth=auth, timeout=8)
            if r.status_code in (200, 201, 204):
                print(f"[OK] Cache cleared via {endpoint.split('/')[-2]}")
                break
        except Exception:
            pass
    for sm in (f"{base}/sitemap.xml", f"{base}/post-sitemap.xml"):
        try:
            requests.get(sm, headers={"Cache-Control": "no-cache"}, timeout=10)
        except Exception:
            pass


def google_indexing_api(client, post_url):
    creds_path = client.google_indexing_credentials
    if not creds_path or not os.path.exists(creds_path):
        return
    try:
        from google.oauth2 import service_account
        import google.auth.transport.requests
    except ImportError:
        print("[WARN] google-auth not installed — skipping Google Indexing API")
        return
    try:
        creds = service_account.Credentials.from_service_account_file(
            creds_path, scopes=["https://www.googleapis.com/auth/indexing"])
        creds.refresh(google.auth.transport.requests.Request())
        r = requests.post("https://indexing.googleapis.com/v3/urlNotifications:publish",
                          json={"url": post_url, "type": "URL_UPDATED"},
                          headers={"Content-Type": "application/json",
                                   "Authorization": f"Bearer {creds.token}"}, timeout=15)
        print(f"[OK] Google Indexing API: {r.status_code}")
    except Exception as e:
        print(f"[WARN] Google Indexing API error: {e}")


def indexnow(client, post_url):
    key = client.indexnow_key
    if not key:
        print("[INFO] No IndexNow key — skipping IndexNow")
        return
    host = urlparse(client.wordpress.site_url).netloc
    payload = {"host": host, "key": key,
               "keyLocation": f"{client.wordpress.site_url}/{key}.txt", "urlList": [post_url]}
    for engine, endpoint in (("IndexNow", "https://api.indexnow.org/indexnow"),
                             ("Bing", "https://www.bing.com/indexnow"),
                             ("Yandex", "https://yandex.com/indexnow")):
        try:
            r = requests.post(endpoint, json=payload,
                              headers={"Content-Type": "application/json"}, timeout=10)
            print(f"[OK] {engine} pinged: {r.status_code}")
        except Exception as e:
            print(f"[WARN] {engine} ping failed: {e}")


def ping_all(client, post_url):
    clear_wp_cache(client)
    google_indexing_api(client, post_url)
    indexnow(client, post_url)
