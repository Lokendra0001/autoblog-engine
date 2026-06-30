"""Per-client configuration: the core of the multi-tenant product.

Everything that was hardcoded for NaviGo in the original single-tenant
``main.py`` lives here as data so the same pipeline can serve any client.

Config is YAML on disk under ``clients/<id>/config.yaml``. Any string value may
contain ``${ENV_VAR}`` which is interpolated from the environment at load time —
use this for secrets (WP application passwords) so they never sit in plain text.
"""

from __future__ import annotations

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
    site_url: str
    username: str
    app_password: str


@dataclass
class Brand:
    name: str
    website: str
    location: str = ""
    voice: str = (
        "confident, clear, and practical — no fluff, no em dashes, no jargon. "
        "Simple British-style English, like explaining to a smart friend who runs a business."
    )
    # Palette drives the generated HTML/CSS template and image prompts.
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
    logo: str = "assets/logo.png"  # relative to the client folder


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
    audience: str = "small business owners and entrepreneurs"
    geo: str = "IN"                       # Google Trends/News geo
    geo_label: str = "India"
    categories: list = field(default_factory=lambda: [
        "AI Tools", "Digital Marketing", "SEO", "Social Media",
        "Business Automation", "Content Marketing", "Paid Advertising",
        "Web Development", "Growth Hacking", "Email Marketing",
    ])
    internal_links: str = ""              # freeform block injected into the writer prompt
    sitemap_url: str = ""                 # used to pull recent posts for dynamic linking
    posts_per_day: int = 1
    topic_mode: str = "trending"          # "trending" | "breaking" | "evergreen_queue"
    min_words: int = 1400
    indexnow_key: str = ""
    google_indexing_credentials: str = "" # path to service-account json (optional)

    # Filled in by the loader, not from YAML:
    config_dir: Path = field(default=None, repr=False)

    @property
    def data_dir(self) -> Path:
        d = DATA_DIR / self.id
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def logo_path(self) -> Path | None:
        if not self.brand.logo:
            return None
        p = (self.config_dir / self.brand.logo) if self.config_dir else Path(self.brand.logo)
        return p if p.exists() else None


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

    raw["wordpress"] = _build(WordPress, raw.get("wordpress", {}))
    raw["brand"] = _build(Brand, raw.get("brand", {}))
    raw["cta"] = _build(CTA, raw.get("cta", {}))
    raw["sources"] = _build(Sources, raw.get("sources", {}))

    client = _build(ClientConfig, raw)
    client.config_dir = cfg_path.parent
    return client


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
