"""Per-client configuration: the core of the multi-tenant product.

Everything that was hardcoded for NaviGo in the original single-tenant
``main.py`` lives here as data so the same pipeline can serve any client.

Config is YAML on disk under ``clients/<id>/config.yaml``. Any string value may
contain ``${ENV_VAR}`` which is interpolated from the environment at load time —
use this for secrets (WP application passwords) so they never sit in plain text.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as e:  # pragma: no cover
    raise SystemExit("PyYAML is required. Run: pip install pyyaml") from e


# Root of the product (parent of the agent/ package).
ROOT = Path(__file__).resolve().parent.parent
CLIENTS_DIR = ROOT / "clients"
DATA_DIR = ROOT / "data"

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _interpolate_env(value: Any) -> Any:
    """Recursively replace ``${VAR}`` tokens in strings with env values."""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.getenv(m.group(1), ""), value)
    if isinstance(value, list):
        return [_interpolate_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _interpolate_env(v) for k, v in value.items()}
    return value


@dataclass
class WordPress:
    site_url: str = ""
    username: str = ""
    app_password: str = ""
    status: str = "publish"        # "publish" (live at once) or "draft"; PUBLISH_STATUS in .env overrides

    @property
    def publish_status(self) -> str:
        return "published" if self.status in ("publish", "published") else "draft"


# Article values the app can send to Strapi -> the field name in your Strapi collection.
# Leave a value empty (or remove it) to not send that value. `title` and `slug` are required.
STRAPI_DEFAULT_FIELDS = {
    "title": "title", "slug": "slug", "content": "content", "image": "image",
    "category": "category", "date": "date", "readTime": "readTime", "imageSource": "imageSource",
    "meta_description": "", "focus_keyword": "", "tags": "",
}


@dataclass
class Strapi:
    """Strapi v5 CMS target (optional)."""
    url: str = ""                  # e.g. https://cms.example.com
    token: str = ""                # API token: find/create (+ update) on the collection, Upload upload
    status: str = "draft"          # "draft" (review in admin, then publish) or "published"; PUBLISH_STATUS overrides
    collection: str = "blogs"      # the collection's API name (plural), as in /api/<collection>
    blog_path: str = "/blogs"      # public URL of a post: brand.website + blog_path + "/" + slug
    fields: dict = field(default_factory=dict)  # overrides for STRAPI_DEFAULT_FIELDS

    @property
    def publish_status(self) -> str:
        return "published" if self.status in ("publish", "published") else "draft"

    def field_map(self) -> dict:
        """Our value name -> Strapi field name, only for values that are sent."""
        return {k: v for k, v in {**STRAPI_DEFAULT_FIELDS, **(self.fields or {})}.items() if v}


@dataclass
class Brand:
    name: str
    website: str
    location: str = ""
    voice: str = (
        "confident, clear, and practical — no fluff, no em dashes, no jargon. "
        "Simple British-style English, like explaining to a smart friend who runs a business."
    )
    # Palette colours the CTA block and the preview page.
    palette: dict = field(default_factory=lambda: {
        "primary": "#1e90ff",
        "deep": "#003C8F",
        "accent": "#1e90ff",
        "bg": "#F9F9F9",
        "text": "#2C2C2C",
        "text_grey": "#555555",
        "light_bg": "#EDF5FF",
    })
    fonts: dict = field(default_factory=lambda: {
        "heading": "Montserrat",
        "body": "Open Sans",
    })


@dataclass
class CTA:
    type: str = "contact"          # "whatsapp" | "contact"
    phone: str = ""                # digits only, country code + number (whatsapp)
    contact_url: str = ""
    headline: str = "Want help putting this into action?"
    subtext: str = "Book a free 30-minute strategy call with our team."
    button_text: str = "Get a Free Consultation"


@dataclass
class Sources:
    """Topic-discovery feeds. Sensible AI/marketing defaults; override per niche."""
    company_feeds: list = field(default_factory=lambda: [
        ["https://openai.com/blog/rss.xml", "OPENAI"],
        ["https://www.anthropic.com/news/rss.xml", "ANTHROPIC"],
        ["https://blog.google/technology/ai/rss/", "GOOGLE AI"],
        ["https://ai.meta.com/blog/rss/", "META AI"],
    ])
    blog_feeds: list = field(default_factory=lambda: [
        ["https://neilpatel.com/blog/feed/", "NEIL PATEL"],
        ["https://blog.hubspot.com/marketing/rss.xml", "HUBSPOT"],
        ["https://www.searchenginejournal.com/feed/", "SEJ"],
        ["https://ahrefs.com/blog/feed/", "AHREFS"],
    ])
    youtube_channels: list = field(default_factory=list)  # [[channel_id, label], ...]
    news_query: str = "AI tools digital marketing 2026"
    news_queries: list = field(default_factory=list)  # extra Google News searches for the niche
    keyword_seeds: list = field(default_factory=list)  # core terms expanded via Google suggestions
    keyword_exclude: list = field(default_factory=list)  # kinds of searches never to plan, e.g. "job vacancies"
    google_trends: bool = True  # general daily trends; turn off for niche B2B topics
    breaking_feeds: list = field(default_factory=lambda: [
        ["https://openai.com/blog/rss.xml", "OPENAI"],
        ["https://www.anthropic.com/news/rss.xml", "ANTHROPIC"],
        ["https://blog.google/technology/ai/rss/", "GOOGLE AI"],
        ["https://blogs.microsoft.com/ai/feed/", "MICROSOFT AI"],
    ])


@dataclass
class ClientConfig:
    id: str
    enabled: bool
    wordpress: WordPress
    brand: Brand
    cta: CTA
    sources: Sources
    strapi: Strapi = field(default_factory=Strapi)
    publish_to: str = ""                  # strapi | wordpress | files ("" = whichever is configured)
    audience: str = "small business owners and entrepreneurs"
    geo: str = "IN"                       # Google Trends/News geo
    geo_label: str = "India"
    categories: list = field(default_factory=lambda: [
        "AI Tools", "Digital Marketing", "SEO", "Social Media",
        "Business Automation", "Content Marketing", "Paid Advertising",
        "Web Development", "Growth Hacking", "Email Marketing",
    ])
    context: str = ""                     # company/product knowledge the writer must rely on
    writing_notes: str = ""               # extra writing rules for this niche (added to the prompt)
    internal_links: str = ""              # freeform block injected into the writer prompt
    sitemap_url: str = ""                 # used to pull recent posts for dynamic linking
    posts_per_day: int = 1
    posts_per_month: int = 8              # monthly planner target (auto mode)
    timezone: str = "Asia/Kolkata"        # the client's local time: decides "today" for the plan
    publish_weekdays: list = field(default_factory=lambda: [1, 4])  # 0=Mon … 6=Sun
    topic_mode: str = "trending"          # "trending" | "breaking" | "evergreen_queue"
    max_news_per_month: int = 1           # publish days that may swap the planned topic for fresh news (0 = never)
    min_words: int = 1400
    max_words: int = 0                    # 0 = no upper limit
    indexnow_key: str = ""
    google_indexing_credentials: str = "" # path to service-account json (optional)

    # Filled in by the loader, not from YAML:
    config_dir: Path = field(default=None, repr=False)
    publish_status_default: str = field(default="", repr=False)  # .env / config.yaml value, before the dashboard setting

    @property
    def destination(self) -> str:
        """Where finished articles go: "strapi", "wordpress" or "files" (saved locally only)."""
        if self.publish_to:
            return self.publish_to
        if self.strapi.url and self.strapi.token:
            return "strapi"
        if self.wordpress.site_url and self.wordpress.app_password:
            return "wordpress"
        return "files"

    @property
    def publish_status(self) -> str:
        """Default status of uploaded articles: "draft" or "published" ("" when saved as files only)."""
        if self.destination == "strapi":
            return self.strapi.publish_status
        if self.destination == "wordpress":
            return self.wordpress.publish_status
        return ""

    @property
    def drafts_dir(self) -> Path:
        """Every article is saved here (.html preview, .json export, .jpg cover), whatever the destination."""
        return self.data_dir / "drafts"

    @property
    def data_dir(self) -> Path:
        d = DATA_DIR / self.id
        d.mkdir(parents=True, exist_ok=True)
        return d


def _build(dataclass_type, data: dict):
    """Instantiate a dataclass from a dict, ignoring unknown keys."""
    known = {f.name for f in fields(dataclass_type)}
    return dataclass_type(**{k: v for k, v in data.items() if k in known})


def load_client(client_id: str) -> ClientConfig:
    cfg_path = CLIENTS_DIR / client_id / "config.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(f"No config for client '{client_id}' at {cfg_path}")

    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    raw = _interpolate_env(raw)
    raw["id"] = client_id

    raw["wordpress"] = _build(WordPress, raw.get("wordpress") or {})
    raw["brand"] = _build(Brand, raw.get("brand", {}))
    raw["cta"] = _build(CTA, raw.get("cta", {}))
    raw["sources"] = _build(Sources, raw.get("sources", {}))
    raw["strapi"] = _build(Strapi, raw.get("strapi") or {})

    client = _build(ClientConfig, raw)
    client.config_dir = cfg_path.parent
    _apply_env_overrides(client)
    client.publish_status_default = client.publish_status
    if (st := load_settings(client_id).get("publish_status")) in PUBLISH_STATUSES:
        set_publish_status(client, st)
    return client


# ── Settings changed from the web dashboard ──────────────────────────────────
# Stored in data/<client>/settings.json, which the web server and the scheduler share, so the next
# scheduled run uses them. They override .env and config.yaml.

def _settings_path(client_id: str) -> Path:
    return DATA_DIR / client_id / "settings.json"


def load_settings(client_id: str) -> dict:
    try:
        data = json.loads(_settings_path(client_id).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def set_publish_status(client, status: str) -> None:
    """Apply "draft" / "published" to whichever CMS the client uses (in memory only)."""
    client.strapi.status = status
    client.wordpress.status = "publish" if status == "published" else "draft"


def save_publish_status(client, status: str) -> None:
    """Dashboard: make `status` the status every scheduled upload uses from now on. Choosing the
    .env / config.yaml value again removes the override, so .env is back in charge."""
    if status not in PUBLISH_STATUSES:
        raise ValueError(f"status must be one of {PUBLISH_STATUSES}, got '{status}'")
    settings = load_settings(client.id)
    if status == client.publish_status_default:
        settings.pop("publish_status", None)
    else:
        settings["publish_status"] = status
    path = _settings_path(client.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    tmp.replace(path)  # atomic: the scheduler never reads a half-written file
    set_publish_status(client, status)


_DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


DESTINATIONS = ("strapi", "wordpress", "files")
PUBLISH_STATUSES = ("draft", "published")


def _apply_env_overrides(client) -> None:
    """PUBLISH_TO, PUBLISH_STATUS, POSTS_PER_MONTH and PUBLISH_DAYS in .env override the client's config."""
    client.publish_to = (os.getenv("PUBLISH_TO", "").strip() or client.publish_to or "").lower()
    if client.publish_to and client.publish_to not in DESTINATIONS:
        raise ValueError(f"publish_to / PUBLISH_TO must be one of {', '.join(DESTINATIONS)}, got '{client.publish_to}'")
    if (st := os.getenv("PUBLISH_STATUS", "").strip().lower()):
        st = "published" if st == "publish" else st
        if st not in PUBLISH_STATUSES:
            raise ValueError(f"PUBLISH_STATUS must be 'draft' or 'published', got '{st}'")
        set_publish_status(client, st)
    if (n := os.getenv("POSTS_PER_MONTH", "").strip()):
        if not n.isdigit() or not 1 <= int(n) <= 31:
            raise ValueError(f"POSTS_PER_MONTH must be a number from 1 to 31, got '{n}'")
        client.posts_per_month = int(n)
    if (days := os.getenv("PUBLISH_DAYS", "").strip()):
        try:
            client.publish_weekdays = sorted({_DAYS[d.strip().lower()[:3]] for d in days.split(",") if d.strip()})
        except KeyError:
            raise ValueError(f"PUBLISH_DAYS must be weekday names like 'tue,fri', got '{days}'") from None


def list_clients(enabled_only: bool = False) -> list[str]:
    if not CLIENTS_DIR.exists():
        return []
    ids = []
    for child in sorted(CLIENTS_DIR.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        if not (child / "config.yaml").exists():
            continue
        if enabled_only:
            try:
                if not load_client(child.name).enabled:
                    continue
            except Exception:
                continue
        ids.append(child.name)
    return ids
