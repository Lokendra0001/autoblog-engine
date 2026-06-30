"""Blog generation: brand-template HTML, internal links, CTA — all from config.

The CSS template, colour palette, fonts, CTA block and internal-link guidance
that were hardcoded for NaviGo are now built from the ClientConfig, so the same
proven prompt structure produces on-brand output for any tenant.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import requests

from .ai import call_ai

_UA = {"User-Agent": "Mozilla/5.0 (compatible; SEOContentAgent/1.0)"}


def build_style(client) -> str:
    """Generate the scoped CSS template from the client's palette + fonts."""
    p = client.brand.palette
    heading = client.brand.fonts.get("heading", "Montserrat")
    body = client.brand.fonts.get("body", "Open Sans")
    return f"""
<style>
:root{{--primary-blue:{p['primary']};--deep-blue:{p['deep']};--accent-orange:{p['accent']};--neutral-bg:{p['bg']};--neutral-white:#FFFFFF;--text-charcoal:{p['text']};--text-grey:{p['text_grey']};--light-blue-bg:{p['light_bg']};}}
body{{margin:0;padding:0;font-family:'{body}',sans-serif;background-color:var(--neutral-bg);color:var(--text-charcoal);line-height:1.6;}}
a{{color:var(--primary-blue);font-weight:700;text-decoration:none;border-bottom:2px solid var(--accent-orange);transition:all .3s ease;}}
a:hover{{color:var(--deep-blue);border-bottom-color:var(--primary-blue);background-color:var(--light-blue-bg);}}
.navigo-container{{font-family:'{body}',sans-serif;background-color:var(--neutral-bg);background-image:radial-gradient(#e5e5e5 1px,transparent 1px);background-size:20px 20px;max-width:900px;margin:40px auto;padding:40px;border-radius:20px;box-shadow:0 10px 30px rgba(0,0,0,.05);position:relative;overflow:hidden;}}
.navigo-shape-top-right{{position:absolute;top:-50px;right:-50px;width:150px;height:150px;background:var(--primary-blue);border-radius:50%;opacity:.1;z-index:0;}}
.navigo-shape-bottom-left{{position:absolute;bottom:-50px;left:-50px;width:200px;height:200px;background:var(--accent-orange);border-radius:50%;opacity:.05;z-index:0;}}
.navigo-hero{{background:var(--neutral-white);padding:45px;border-radius:15px;box-shadow:0 4px 15px rgba(0,0,0,.03);border-left:6px solid var(--primary-blue);margin-bottom:40px;position:relative;z-index:1;}}
.navigo-logo{{font-family:'{heading}',sans-serif;font-weight:800;background:var(--light-blue-bg);padding:6px 12px;border-radius:4px;color:var(--deep-blue);letter-spacing:1px;font-size:1rem;margin-bottom:18px;display:inline-block;}}
.navigo-hero h1{{font-family:'{heading}',sans-serif;font-size:2rem;margin:0 0 12px;color:var(--text-charcoal);line-height:1.3;}}
.navigo-hero p{{font-size:1.05rem;color:var(--text-grey);line-height:1.7;margin:0 0 12px;max-width:760px;}}
.navigo-article{{background:var(--neutral-white);padding:35px;border-radius:12px;border:1px solid #e5e5e5;line-height:1.9;font-size:1.06rem;color:var(--text-grey);position:relative;z-index:1;}}
.navigo-article h2{{font-family:'{heading}',sans-serif;color:var(--deep-blue);font-size:1.6rem;margin-top:34px;margin-bottom:12px;}}
.navigo-article h3{{font-family:'{heading}',sans-serif;color:var(--text-charcoal);font-size:1.2rem;margin-top:22px;margin-bottom:8px;}}
.navigo-article p{{margin-bottom:14px;}}
.navigo-article ul{{margin-left:18px;margin-bottom:14px;}}
.navigo-article table{{width:100%;border-collapse:collapse;margin:20px 0;}}
.navigo-article th,.navigo-article td{{border:1px solid #e5e5e5;padding:12px;text-align:left;}}
.navigo-article th{{background-color:#f2f2f2;color:var(--deep-blue);}}
.key-takeaways{{background:var(--light-blue-bg);border-left:6px solid var(--primary-blue);padding:18px 22px;border-radius:8px;margin:28px 0;}}
.toc{{background:#fafafa;border:1px solid #eee;padding:20px;border-radius:8px;margin:25px 0;}}
.toc strong{{display:block;margin-bottom:10px;font-family:'{heading}',sans-serif;color:var(--deep-blue);}}
.toc ul{{list-style-type:none;padding-left:0;margin:0;}}
.toc li{{margin-bottom:8px;padding-left:15px;position:relative;}}
.toc li::before{{content:"•";color:var(--primary-blue);position:absolute;left:0;top:0;}}
.navigo-faq-header{{text-align:center;margin-top:42px;margin-bottom:22px;}}
.navigo-faq-header h2{{font-family:'{heading}',sans-serif;font-size:1.9rem;color:var(--text-charcoal);}}
.navigo-faq-details{{background:var(--neutral-white);margin-bottom:12px;border-radius:8px;border:1px solid #e5e5e5;overflow:hidden;position:relative;z-index:1;}}
.navigo-faq-summary{{padding:16px 20px;font-family:'{heading}',sans-serif;font-weight:700;color:var(--deep-blue);cursor:pointer;display:flex;justify-content:space-between;align-items:center;list-style:none;}}
.navigo-faq-summary::after{{content:'';width:10px;height:10px;border-right:3px solid var(--primary-blue);border-bottom:3px solid var(--primary-blue);transform:rotate(45deg);flex-shrink:0;}}
.navigo-faq-details[open] .navigo-faq-summary::after{{transform:rotate(-135deg);}}
.navigo-faq-answer{{padding:0 20px 18px;color:var(--text-grey);}}
.navigo-footer{{margin-top:36px;padding-top:22px;border-top:2px solid #eee;text-align:center;color:var(--text-grey);font-size:.95rem;position:relative;z-index:1;}}
@media(max-width:768px){{.navigo-container{{padding:20px;margin:0;border-radius:0;}}.navigo-hero{{padding:25px;}}.navigo-article{{padding:20px;font-size:1rem;}}.navigo-shape-top-right,.navigo-shape-bottom-left{{display:none;}}}}
</style>
<link href="https://fonts.googleapis.com/css2?family={heading.replace(' ', '+')}:wght@400;700;800&family={body.replace(' ', '+')}:wght@400;600;700&display=swap" rel="stylesheet">
"""


def build_cta(client) -> str:
    cta = client.cta
    if cta.type == "whatsapp" and cta.phone:
        href = (f"https://wa.me/{cta.phone}?text=Hi%2C%20I%20read%20your%20blog%20"
                f"and%20want%20a%20free%20strategy%20call")
        bg = "linear-gradient(135deg,#25D366 0%,#128C7E 100%)"
        btn_color = "#128C7E"
    else:
        href = cta.contact_url or client.brand.website
        bg = f"linear-gradient(135deg,{client.brand.palette['primary']} 0%,{client.brand.palette['deep']} 100%)"
        btn_color = client.brand.palette["deep"]
    heading = client.brand.fonts.get("heading", "Montserrat")
    return f"""
<div style="background:{bg};border-radius:12px;padding:24px 28px;margin:32px 0;text-align:center;position:relative;z-index:1;">
  <p style="color:#fff;font-family:'{heading}',sans-serif;font-weight:800;font-size:1.15rem;margin:0 0 8px;">{cta.headline}</p>
  <p style="color:rgba(255,255,255,0.9);font-size:0.95rem;margin:0 0 16px;">{cta.subtext}</p>
  <a href="{href}" target="_blank" rel="noopener" style="background:#fff;color:{btn_color};font-family:'{heading}',sans-serif;font-weight:800;padding:12px 28px;border-radius:50px;text-decoration:none;font-size:1rem;border-bottom:none;display:inline-block;">{cta.button_text}</a>
</div>
"""


def get_recent_blog_links(client, limit=10) -> str:
    if not client.sitemap_url:
        return ""
    try:
        r = requests.get(client.sitemap_url, timeout=12, verify=False, headers=_UA)
        if r.status_code != 200:
            return ""
        root = ET.fromstring(r.content)
        ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        items = []
        for u in root.findall(f".//{ns}url"):
            loc = (u.findtext(f"{ns}loc", "") or "").strip()
            lastmod = (u.findtext(f"{ns}lastmod", "") or "").strip()
            if loc:
                items.append((lastmod, loc))
        items.sort(reverse=True)
        lines = []
        for _, loc in items[:limit]:
            slug = loc.rstrip("/").rsplit("/", 1)[-1]
            anchor = re.sub(r"-\d+$", "", slug).replace("-", " ").title()
            lines.append(f"- {anchor}: {loc}")
        return "\n".join(lines)
    except Exception as e:
        print(f"[WARN] Dynamic internal links fetch failed: {e}")
        return ""


def generate_blog(client, keyword: str, research: str = ""):
    """Returns (title, content_html, meta, focus_keyword, category, tags)."""
    system_prompt = (
        f"You are an expert SEO blog writer for {client.brand.name}, serving {client.audience} "
        f"in {client.geo_label}. Tone: {client.brand.voice} "
        "Always respond using the exact delimiter format requested — no markdown, no code fences."
    )

    research_block = (f"\n\nRESEARCH DATA (use for fresh, accurate facts):\n{research}\n" if research else "")

    static_links = (f"\nINTERNAL LINKS TO USE (insert 2-3 contextually with natural anchor text):\n{client.internal_links}\n"
                    if client.internal_links else "")
    categories = ", ".join(client.categories)

    # Static spec -> goes in the system prefix (cache-eligible). The variable
    # inputs (keyword, fresh research, dynamic recent links) go in the short user
    # message at the end, so this large template is billed once then read from cache.
    spec = f"""BRAND CONTEXT:
- Brand: {client.brand.name}
- Website: {client.brand.website}
- Location: {client.brand.location or client.geo_label}
- Target audience: {client.audience}
{static_links}
STYLE RULES:
1. Structure: Hero intro -> Key Takeaways -> Table of Contents -> 5 content sections (h2 + h3) -> Comparison table -> FAQ (4 questions) -> CTA footer
2. Each section: minimum 120 words, practical {client.geo_label}-relevant examples, numbered steps where useful
3. Use <strong> for key terms
4. Include 1 HTML table
5. Internal links use natural anchor text
6. No em dashes. No filler openers.
7. Minimum {client.min_words} words total
8. Include exactly 2 image placeholders in the body (after Section 2 and after Section 4), each in this exact format: [IMAGE_PLACEHOLDER: detailed description of a clean modern business infographic on a white background that visually explains this section, with short legible correctly-spelled labels, premium professional colours, and concrete structural elements like numbered cards or simple bar charts.]

HTML TEMPLATE TO FILL IN EXACTLY (use these class names exactly; styling is external):

<div class="navigo-container">
  <div class="navigo-shape-top-right"></div>
  <div class="navigo-shape-bottom-left"></div>
  <div class="navigo-hero">
    <div class="navigo-logo">{client.brand.name}</div>
    <h1>[SEO HEADLINE — include keyword naturally, 60-70 chars]</h1>
    <p>[2-3 sentence hook with <strong> on 1-2 key phrases.]</p>
    <p>This guide covers:</p>
    <ul><li>[Point 1]</li><li>[Point 2]</li><li>[Point 3]</li><li>[Point 4]</li></ul>
    <p>[1 sentence leading into the article.]</p>
  </div>
  <div class="navigo-article">
    <div class="key-takeaways"><strong>What You'll Learn:</strong>
      <ul><li>[Takeaway 1]</li><li>[Takeaway 2]</li><li>[Takeaway 3]</li><li>[Takeaway 4]</li></ul>
    </div>
    <div class="toc"><strong>Table of Contents</strong>
      <ul>
        <li><a href="#section-1">[Section 1 Title]</a></li>
        <li><a href="#section-2">[Section 2 Title]</a></li>
        <li><a href="#section-3">[Section 3 Title]</a></li>
        <li><a href="#section-4">[Section 4 Title]</a></li>
        <li><a href="#section-5">[Section 5 Title]</a></li>
      </ul>
    </div>
    <h2 id="section-1">[What is — plain explanation]</h2>
    [3-4 paragraphs.]
    <h2 id="section-2">[Why It Matters]</h2>
    [3-4 h3 subheadings, each 80-100 words.]
    [IMAGE_PLACEHOLDER: list-based infographic of why this matters, numbered colored icons, clean white background, premium colours.]
    <h2 id="section-3">[Step-by-Step Guide]</h2>
    [Numbered steps as ul with <strong> labels, each 60-80 words.]
    <h2 id="section-4">[Common Mistakes to Avoid]</h2>
    [h3 per mistake. Include 1-2 internal links.]
    [IMAGE_PLACEHOLDER: 2-column comparison grid, Mistakes (red X) vs Best Practices (green check), clean white background.]
    <h2 id="section-5">[Comparison or Tools Overview]</h2>
    [1-2 paragraphs then:]
    <table><thead><tr><th>[Col1]</th><th>[Col2]</th><th>[Col3]</th><th>[Col4]</th></tr></thead>
      <tbody>[5-6 rows of real data]</tbody></table>
    [1 closing paragraph with an internal link.]
  </div>
  <div class="navigo-faq-header"><h2>Frequently Asked Questions</h2></div>
  <details class="navigo-faq-details"><summary class="navigo-faq-summary">[Q1]</summary><div class="navigo-faq-answer">[A1]</div></details>
  <details class="navigo-faq-details"><summary class="navigo-faq-summary">[Q2]</summary><div class="navigo-faq-answer">[A2]</div></details>
  <details class="navigo-faq-details"><summary class="navigo-faq-summary">[Q3]</summary><div class="navigo-faq-answer">[A3]</div></details>
  <details class="navigo-faq-details"><summary class="navigo-faq-summary">[Q4]</summary><div class="navigo-faq-answer">[A4]</div></details>
  <div class="navigo-footer">
    <p>[1 strong benefit-driven CTA line]</p>
    <p><a href="{client.cta.contact_url or client.brand.website}" target="_blank">{client.cta.button_text} — {client.brand.name}</a></p>
  </div>
</div>

Respond using EXACTLY this format (no JSON, no code fences):

===TITLE===
[SEO title 60-70 chars, keyword included]
===TITLE_END===
===META===
[Meta description 150-160 chars, keyword + benefit]
===META_END===
===FOCUS_KEYWORD===
[2-5 word focus keyword]
===FOCUS_KEYWORD_END===
===CATEGORY===
[ONE of: {categories}]
===CATEGORY_END===
===TAGS===
[8-10 comma-separated tags]
===TAGS_END===
===CONTENT===
[The complete filled-in HTML, no placeholders remaining except the 2 IMAGE_PLACEHOLDER blocks]
===CONTENT_END==="""

    # Variable inputs only — keep this short so the cached static prefix dominates.
    recent = get_recent_blog_links(client)
    recent_block = (f"RECENT POSTS (link to the most relevant 1-2):\n{recent}\n\n" if recent else "")
    user_prompt = (f"{research_block}{recent_block}"
                   f'Now write the complete SEO blog post for the keyword: "{keyword}". '
                   "Follow the template and the output format exactly.")

    raw = call_ai(messages=[{"role": "user", "content": user_prompt}],
                  system=system_prompt + "\n\n" + spec, max_tokens=8192,
                  tier="smart", cache_system=True)

    def extract(tag):
        start = raw.find(f"==={tag}===")
        end = raw.find(f"==={tag}_END===")
        if start == -1 or end == -1:
            raise ValueError(f"Missing delimiter ==={tag}=== in AI response")
        return raw[start + len(f"==={tag}==="):end].strip()

    title = extract("TITLE")
    meta = extract("META")
    focus_keyword = extract("FOCUS_KEYWORD")
    category = extract("CATEGORY")
    tags = [t.strip() for t in extract("TAGS").split(",") if t.strip()]
    content = extract("CONTENT")

    # Inject CTA before the FAQ (highest-intent moment)
    cta_html = build_cta(client)
    faq_marker = '<div class="navigo-faq-header"'
    if faq_marker in content:
        content = content.replace(faq_marker, cta_html + "\n" + faq_marker, 1)
    else:
        footer_marker = '<div class="navigo-footer"'
        if footer_marker in content:
            content = content.replace(footer_marker, cta_html + "\n" + footer_marker, 1)

    content = build_style(client) + "\n" + content
    return title, content, meta, focus_keyword, category, tags
