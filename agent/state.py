"""Per-client persistent state: used topics, posted headlines, dedupe, GSC queue.

Each client gets its own namespace under data/<client_id>/ so dedupe history
never bleeds across tenants.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone


class ClientState:
    def __init__(self, client):
        self.client = client
        self.dir = client.data_dir
        self.used_topics_file = self.dir / "used_topics.txt"
        self.headlines_file = self.dir / "posted_headlines.txt"
        self.queue_file = self.dir / "keywords_queue.txt"
        self.gsc_queue_file = self.dir / "gsc_retry_queue.json"
        self.log_file = self.dir / "published.jsonl"

    # ── used topics / dedupe ──────────────────────────────────────────────
    def load_used_topics(self) -> list[str]:
        if not self.used_topics_file.exists():
            return []
        return [l.strip() for l in self.used_topics_file.read_text(encoding="utf-8").splitlines() if l.strip()]

    def save_used_topic(self, topic: str):
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self.used_topics_file.open("a", encoding="utf-8") as f:
            f.write(f"{date_str} | {topic}\n")

    @staticmethod
    def is_duplicate(new_topic: str, used_lines: list[str]) -> bool:
        stopwords = {
            "a", "an", "the", "and", "or", "for", "in", "on", "of", "to", "is", "it",
            "how", "what", "why", "with", "from", "by", "at", "this", "that", "your",
            "2026", "2025", "business", "businesses", "small", "best", "top", "guide",
            "complete", "full", "tips", "strategy", "ways", "just", "launched", "release",
            "update", "new", "know", "need", "needs", "work", "works", "using", "use",
            "get", "make", "about", "will", "has", "have", "been", "into", "their",
            "which", "when", "every", "also", "more",
        }

        def keywords(text):
            words = re.findall(r"[a-z]+", text.lower())
            return {w for w in words if w not in stopwords and len(w) > 3}

        new_keys = keywords(new_topic)
        for line in used_lines:
            topic = line.split(" | ", 1)[-1] if " | " in line else line
            if len(new_keys & keywords(topic)) >= 3:
                return True
        return False

    # ── posted headlines (breaking-news dedupe) ───────────────────────────
    @staticmethod
    def headline_sig(h: str) -> str:
        h = re.sub(r"^\[[^\]]+\]\s*", "", h)
        return re.sub(r"[^a-z0-9]+", " ", h.lower()).strip()

    def load_posted_headlines(self) -> set[str]:
        if not self.headlines_file.exists():
            return set()
        return {l.strip() for l in self.headlines_file.read_text(encoding="utf-8").splitlines() if l.strip()}

    def record_posted_headlines(self, sigs):
        existing = []
        if self.headlines_file.exists():
            existing = [l.strip() for l in self.headlines_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        for sig in sigs:
            if sig and sig not in existing:
                existing.append(sig)
        self.headlines_file.write_text("\n".join(existing[-200:]) + "\n", encoding="utf-8")

    # ── evergreen keyword queue ───────────────────────────────────────────
    def next_queued_keyword(self):
        if not self.queue_file.exists():
            return None
        lines = [l.strip() for l in self.queue_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        if not lines:
            return None
        self.queue_file.write_text("\n".join(lines[1:]) + ("\n" if lines[1:] else ""), encoding="utf-8")
        return lines[0]

    # ── published log (for reporting) ─────────────────────────────────────
    def log_published(self, record: dict):
        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ── GSC retry queue ───────────────────────────────────────────────────
    def load_gsc_queue(self) -> list:
        try:
            return json.loads(self.gsc_queue_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def save_gsc_queue(self, queue):
        self.gsc_queue_file.write_text(json.dumps(queue, indent=2), encoding="utf-8")
