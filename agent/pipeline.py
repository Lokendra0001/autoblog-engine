"""Orchestrates one full run for a single client: the productized NaviGo pipeline.

run_once(client, ...) does: topic -> research -> write -> images -> publish ->
schema -> index -> log. Every step that can fail without invalidating the post
is non-fatal, matching the original's resilience.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from . import images, indexer, publisher, research as research_mod, trends, writer
from .state import ClientState


def _inject_inline_images(client, content, focus_keyword):
    placeholders = re.findall(r"\[IMAGE_PLACEHOLDER:\s*(.*?)\]", content)
    print(f"[IMAGE] {len(placeholders)} inline placeholder(s)")
    for i, prompt in enumerate(placeholders[:2]):
        prompt = prompt.strip()
        media_id, img_url = None, None
        img_bytes = images.generate_image(client, prompt, featured=False)
        if img_bytes:
            media_id, img_url = publisher.upload_image_bytes(
                client, img_bytes, f"{focus_keyword}-{i+1}",
                alt_text=f"{focus_keyword}: {prompt[:80]}")
        if not media_id:
            url, photographer = images.fetch_pexels_image(prompt)
            if url:
                media_id, img_url = publisher.upload_image_url(client, url, f"{focus_keyword}-{i+1}", photographer)
        if img_url:
            block = (f'\n<figure class="wp-block-image size-large" style="margin:32px 0;text-align:center;">'
                     f'<img src="{img_url}" alt="{prompt}" style="border-radius:12px;max-width:100%;height:auto;'
                     f'box-shadow:0 4px 15px rgba(0,0,0,0.08);"/></figure>\n')
            content = re.sub(r"\[IMAGE_PLACEHOLDER:\s*" + re.escape(prompt) + r"\]", block, content, count=1)
        else:
            content = re.sub(r"\[IMAGE_PLACEHOLDER:\s*" + re.escape(prompt) + r"\]", "", content, count=1)
    return content


def run_once(client, keyword=None, dry_run=False):
    """Generate (and unless dry_run, publish) one post for the client."""
    state = ClientState(client)

    # 1. Topic
    if keyword:
        print(f"[MODE] Custom keyword: {keyword}")
    elif client.topic_mode == "breaking":
        keyword = trends.detect_breaking_news(client, state)
        if not keyword:
            print("[OK] No breaking news. Nothing to post.")
            return None
    elif client.topic_mode == "evergreen_queue":
        keyword = state.next_queued_keyword()
        if not keyword:
            print("[WARN] Evergreen queue empty.")
            return None
    else:  # trending
        keyword = trends.discover_topic(client, state)
        if not keyword:
            keyword = state.next_queued_keyword()
        if not keyword:
            print("[WARN] No topic available.")
            return None

    # 2. Research
    research_text = research_mod.research_topic(client, keyword)

    # 3. Write
    title, content, meta, focus_keyword, category, tags = writer.generate_blog(client, keyword, research_text)
    word_count = len(re.sub(r"<[^>]+>", "", content).split())
    print(f"[OK] {title} | {word_count} words | {category}")

    # Dry run: save HTML to disk for client approval, no publish.
    if dry_run:
        out = client.data_dir / "drafts"
        out.mkdir(exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", keyword.lower())[:50].strip("-")
        path = out / f"{datetime.now().strftime('%Y%m%d-%H%M')}-{slug}.html"
        # Inline images skipped in dry-run (placeholders left as comments for the reviewer)
        preview = content.replace("[IMAGE_PLACEHOLDER:", "<!-- IMAGE: ").replace("]", " -->")
        path.write_text(preview, encoding="utf-8")
        print(f"[DRY-RUN] Draft saved: {path}")
        return {"keyword": keyword, "title": title, "draft": str(path)}

    # 4. Featured image (non-fatal)
    featured_media_id = None
    try:
        fb = images.generate_image(client, title, featured=True)
        if fb:
            featured_media_id, _ = publisher.upload_image_bytes(
                client, fb, focus_keyword or title, alt_text=title)
        if not featured_media_id:
            url, photographer = images.fetch_pexels_image(keyword)
            if url:
                featured_media_id, _ = publisher.upload_image_url(client, url, focus_keyword or title, photographer)
    except Exception as e:
        print(f"[WARN] Featured image step failed: {e}")

    # 5. Inline images (non-fatal)
    try:
        content = _inject_inline_images(client, content, focus_keyword)
    except Exception as e:
        print(f"[WARN] Inline image step failed: {e}")

    # 6. Publish
    post_id, post_url = publisher.publish_post(
        client, title, content, meta, focus_keyword, category, tags, featured_media_id)

    # 7. Schema (non-fatal)
    try:
        publisher.patch_content(client, post_id, publisher.build_schema(client, title, meta, content, post_url))
    except Exception as e:
        print(f"[WARN] Schema injection failed: {e}")

    # Record topic immediately so dedupe holds even if indexing fails
    state.save_used_topic(keyword)

    # 8. Index (non-fatal)
    try:
        indexer.ping_all(client, post_url)
    except Exception as e:
        print(f"[WARN] Indexing failed: {e}")

    # 9. Log
    state.log_published({
        "ts": datetime.now(timezone.utc).isoformat(), "keyword": keyword,
        "title": title, "url": post_url, "post_id": post_id,
        "word_count": word_count, "category": category,
    })
    print(f"[OK] [{client.id}] DONE: {post_url}")
    return {"keyword": keyword, "title": title, "url": post_url, "post_id": post_id}
