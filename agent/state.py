"""Per-client persistent state: used topics, posted headlines, dedupe, GSC queue.

Each client gets its own namespace under data/<client_id>/ so dedupe history
never bleeds across tenants.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone


_STOPWORDS = {
    "the", "and", "for", "with", "from", "how", "what", "why", "when", "which", "this", "that", "your",
    "its", "into", "about", "are", "can", "use", "using", "vs", "versus", "guide", "complete", "best",
    "top", "tips", "ways", "new", "india", "indian", "2025", "2026", "2027",
}


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
    def topic_words(text: str) -> set[str]:
        """Meaningful words of a topic/title, lightly stemmed ("designing" ~ "design", "tanks" ~ "tank")."""
        words = set()
        for w in re.findall(r"[a-z0-9]+", text.lower()):
            if w in _STOPWORDS or len(w) < 3:
                continue
            for suffix in ("ing", "es", "s"):
                if w.endswith(suffix) and len(w) - len(suffix) >= 4:
                    w = w[: -len(suffix)]
                    break
            words.add(w)
        return words

    @classmethod
    def similar(cls, a: str, b: str) -> bool:
        """Same topic? Most meaningful words of the shorter phrase appear in the other one.
        "GFRP rebar for water tanks" ~ "GFRP Rebar for Water Tanks: Corrosion-Free Reinforcement",
        but not ~ "GFRP Rebar for Bridge Decks"."""
        wa, wb = cls.topic_words(a), cls.topic_words(b)
        small = min(len(wa), len(wb))
        if small == 0:
            return False
        shared = len(wa & wb)
        if small < 3:
            return wa == wb
        return shared >= max(3, math.ceil(0.75 * small))

    @classmethod
    def is_duplicate(cls, new_topic: str, used_lines: list[str]) -> bool:
        return any(cls.similar(new_topic, line.split(" | ", 1)[-1]) for line in used_lines)

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
