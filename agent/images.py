"""Image generation: Gemini Imagen (branded) with logo overlay, Pexels fallback.

Generalized from the NaviGo pipeline. The brand style guide for the image prompt
is derived from the client's palette description; the client's own logo is
overlaid afterwards so generated images never need to render text branding.
"""

from __future__ import annotations

import io
import os
import re

import requests

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")

_UA = {"User-Agent": "Mozilla/5.0 (compatible; SEOContentAgent/1.0)"}


def _brand_style(client) -> str:
    return (
        "Clean minimal white background, modern flat vector or 3D isometric business "
        "graphic style, sharp clean shapes, professional high-trust corporate aesthetic. "
        "Strictly no hex codes, no colour-code text, no hash symbols anywhere. "
        "Extremely clean, highly legible typography, correct spelling. "
        "CRITICAL: the image must contain NO logos and NO company name or wordmark of any "
        "kind — the official logo is added separately afterwards. Keep on-image text minimal: "
        "only short, real, correctly spelled English words where essential."
    )


def _overlay_logo(img_bytes, client):
    logo_path = client.logo_path
    if not logo_path:
        return img_bytes
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        logo = Image.open(logo_path).convert("RGBA")
        logo_h = 64
        logo_w = int(logo.width * (logo_h / logo.height))
        logo_resized = logo.resize((logo_w, logo_h), Image.Resampling.LANCZOS)
        pad = 24
        img.paste(logo_resized, (img.width - logo_w - pad, pad), logo_resized)
        out = io.BytesIO()
        img.convert("RGB").save(out, format="JPEG", quality=95)
        return out.getvalue()
    except Exception as e:
        print(f"[WARN] Logo overlay failed: {e}")
        return img_bytes


def generate_image(client, prompt_subject, featured=False):
    """Generate a branded image via Gemini Imagen. Returns JPEG bytes or None."""
    if not GEMINI_API_KEY:
        return None
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("[WARN] google-genai not installed — skipping AI images")
        return None
    try:
        subject = re.sub(r"#[0-9A-Fa-f]{3,6}\b", "", prompt_subject).strip()
        if featured:
            prompt = (f"A modern premium business infographic representing: {subject}. "
                      f"16:9 aspect ratio blog header. {_brand_style(client)}")
        else:
            prompt = f"{subject}. {_brand_style(client)}"
        client_g = genai.Client(api_key=GEMINI_API_KEY)
        resp = client_g.models.generate_images(
            model="imagen-4.0-generate-001", prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1, aspect_ratio="16:9", output_mime_type="image/jpeg"),
        )
        if resp.generated_images:
            return _overlay_logo(resp.generated_images[0].image.image_bytes, client)
    except Exception as e:
        print(f"[WARN] Gemini image generation failed: {e}")
    return None


def fetch_pexels_image(keyword):
    if not PEXELS_API_KEY:
        return None, None
    try:
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={"query": " ".join(keyword.split()[:4]), "per_page": 3, "orientation": "landscape"},
            timeout=15)
        if resp.status_code != 200:
            return None, None
        photos = resp.json().get("photos", [])
        if not photos:
            return None, None
        return photos[0]["src"]["large2x"], photos[0].get("photographer", "Pexels")
    except Exception as e:
        print(f"[WARN] Pexels fetch failed: {e}")
        return None, None
