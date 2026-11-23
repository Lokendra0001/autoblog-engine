"""Article generation: research-grounded draft -> rule checks + AI editor review -> rewrite.

Output is clean, semantic HTML (h2/h3/p/ul/ol/blockquote/table) with no <h1> and no
embedded CSS, so a CMS can render it with its own styles and show the title as the
page's only H1. The first paragraph doubles as the meta description, because many
sites derive the description from the content.
"""

from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import requests

from .ai import call_ai

_UA = {"User-Agent": "Mozilla/5.0 (compatible; AutoBlogEngine/1.0)"}

MAX_DRAFTS = 3     # first draft + up to 2 rewrites
PASS_SCORE = 8     # editor score (out of 10) needed to accept a draft

_BANNED = ["in today's", "fast-paced", "game-changer", "game changer", "revolutionary", "unlock",
           "dive into", "delve", "look no further", "it's important to note", "in conclusion",
           "elevate", "seamless"]


@dataclass
class Article:
    title: str
    meta: str
    focus_keyword: str
    category: str
    tags: list = field(default_factory=list)
    featured_query: str = ""   # stock-photo search phrase for the header image
    content: str = ""          # semantic HTML body (no h1)
    review_score: int = 0      # final editor score (1-10) of the chosen draft
    review_notes: list = field(default_factory=list)  # remaining editor/rule notes, for the reviewer


# ── helpers shared with the pipeline/publisher ────────────────────────────────

def text_of(html_str: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_str))).strip()


def faq_items(content: str) -> list[tuple[str, str]]:
    """(question, answer) pairs from the FAQ section: <h3>Q</h3> followed by <p>A</p>."""
    m = re.search(r'<h2[^>]*id="faqs"[^>]*>.*?</h2>(.*)', content, re.S)
    if not m:
        return []
    pairs = re.findall(r"<h3[^>]*>(.*?)</h3>\s*<p[^>]*>(.*?)</p>", m.group(1), re.S)
    return [(text_of(q), text_of(a)) for q, a in pairs if text_of(q) and text_of(a)]


def faq_schema(content: str) -> str:
    """FAQPage JSON-LD for the article's FAQ section (empty string if none)."""
    items = faq_items(content)
    if not items:
        return ""
    data = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
        for q, a in items]}
    return f'<script type="application/ld+json">{json.dumps(data, ensure_ascii=False)}</script>'


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


def build_cta(client) -> str:
    """Call-to-action block with inline styles, so it renders on any site."""
    cta, p = client.cta, client.brand.palette
    href = cta.contact_url or client.brand.website
    if cta.type == "whatsapp" and cta.phone:
        href = f"https://wa.me/{cta.phone}"
    return (f'<div style="background:{p["primary"]};border-radius:12px;padding:24px 28px;margin:40px 0;text-align:center;">'
            f'<p style="color:#fff;font-weight:700;font-size:1.2rem;margin:0 0 8px;">{html.escape(cta.headline)}</p>'
            f'<p style="color:rgba(255,255,255,.9);margin:0 0 16px;">{html.escape(cta.subtext)}</p>'
            f'<a href="{href}" style="display:inline-block;background:{p["accent"]};color:{p["deep"]};'
            f'font-weight:700;padding:12px 28px;border-radius:50px;text-decoration:none;">'
            f'{html.escape(cta.button_text)}</a></div>')


def _style_tables(content: str) -> str:
    """Tables get inline styles: CMS content styles rarely cover them."""
    content = re.sub(r"<table[^>]*>", '<div style="overflow-x:auto;margin:24px 0;"><table style="width:100%;'
                     'border-collapse:collapse;font-size:0.95rem;">', content)
    content = content.replace("</table>", "</table></div>")
    content = re.sub(r"<th(\s[^>]*)?>", '<th style="text-align:left;padding:12px;border:1px solid #e5e7eb;'
                     'background:#f3f6fb;">', content)
    return re.sub(r"<td(\s[^>]*)?>", '<td style="padding:12px;border:1px solid #e5e7eb;vertical-align:top;">',
                  content)


# ── draft parsing and automatic fixes ─────────────────────────────────────────

def _parse(raw: str, keyword: str) -> Article:
    """Read the ===TAG=== sections. Tolerates spacing/case slips and a missing _END marker;
    only TITLE and CONTENT are required."""
    def extract(tag, required=True):
        m = re.search(rf"===\s*{tag}\s*===(.*?)(?====\s*{tag}_END\s*===|===\s*[A-Z_]+\s*===|\Z)",
                      raw, re.S | re.I)
        if not m or not m.group(1).strip():
            if required:
                raise ValueError(f"Missing section ==={tag}=== in AI response")
            return ""
        return m.group(1).strip()

    return Article(
        title=extract("TITLE"), meta=extract("META", False),
        focus_keyword=extract("FOCUS_KEYWORD", False) or keyword,
        category=extract("CATEGORY", False),
        tags=[t.strip() for t in extract("TAGS", False).split(",") if t.strip()],
        featured_query=extract("FEATURED_IMAGE", False) or keyword,
        content=extract("CONTENT"))


def _fix_dashes(a: Article) -> Article:
    """House style bans em dashes: replace them mechanically rather than paying for a rewrite."""
    def fix(t):
        return re.sub(r"\s*—\s*", ", ", t)
    a.title, a.meta, a.content = fix(a.title), fix(a.meta), fix(a.content)
    a.tags = [fix(t) for t in a.tags]
    return a


_SMALL_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into", "nor", "of", "on",
                "or", "per", "the", "to", "via", "vs", "with"}


def _word_forms(text: str) -> dict[str, str]:
    """lowercase word -> how the text usually writes it ("gfrp" -> "GFRP", "india" -> "India")."""
    counts: dict[str, dict[str, int]] = {}
    for w in re.findall(r"[A-Za-z][A-Za-z0-9]*", text):
        forms = counts.setdefault(w.lower(), {})
        forms[w] = forms.get(w, 0) + 1
    return {low: max(forms, key=forms.get) for low, forms in counts.items()}


def cased_keyword(keyword: str, text: str) -> str:
    """The keyword with each word cased the way `text` writes it: "gfrp rebar market india" ->
    "GFRP rebar market India". Words the text never uses keep the casing they were typed in."""
    forms = _word_forms(text)
    return re.sub(r"[A-Za-z][A-Za-z0-9]*", lambda m: forms.get(m.group(0).lower(), m.group(0))
                  if m.group(0).islower() else m.group(0), keyword)


def title_case(title: str, text: str = "") -> str:
    """Title Case that keeps acronyms: words written in capitals in `text` (GFRP, IS, IRC) stay so,
    small words stay lowercase except first and after a colon."""
    forms = _word_forms(text)
    out, start = [], True
    for token in title.split(" "):
        def fix(m, first=start):
            w = m.group(0)
            known = forms.get(w.lower(), "")
            if known and known[1:] != known[1:].lower():  # acronym or mixed case in the text: GFRP, IoT
                return known
            if w != w.lower():                             # already has capitals: leave it
                return w
            return w if (w in _SMALL_WORDS and not first) else w[0].upper() + w[1:]
        out.append(re.sub(r"[A-Za-z][A-Za-z0-9]*", fix, token, count=1) if token else token)
        # later parts of a hyphenated word (corrosion-free -> Corrosion-Free)
        out[-1] = re.sub(r"(?<=-)([a-z])", lambda m: m.group(1).upper(), out[-1])
        if token:
            start = token.endswith(":")
    return " ".join(out)


def _fix_case(a: Article, keyword: str) -> Article:
    """Models copy the keyword exactly as typed ("gfrp rebar market india"). Write it the way the
    article does, Title Case the title and start every heading, paragraph and list item with a capital."""
    body = text_of(a.content)
    shown = cased_keyword(keyword, body)
    pattern = re.compile(rf"(?<![A-Za-z0-9-]){re.escape(keyword)}(?![A-Za-z0-9-])", re.I)

    def recase(m):  # add missing capitals; keep capitals already there (sentence start, Title Case headings)
        return "".join(f.upper() if w.isupper() else f for f, w in zip(m.group(0), shown))
    a.content = pattern.sub(recase, a.content)
    a.meta = pattern.sub(recase, a.meta)
    a.content = re.sub(r"(<(?:h[23]|p|li)(?:\s[^>]*)?>\s*)([a-z])", lambda m: m.group(1) + m.group(2).upper(), a.content)
    a.title = title_case(a.title, body)
    if a.meta:
        a.meta = a.meta[0].upper() + a.meta[1:]
    return a


_FIRST_P = re.compile(r"<p[^>]*>(.*?)</p>", re.S)


def _norm(t: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", t.lower()))


def _title_ok(title: str, keyword: str) -> bool:
    return 30 <= len(title) <= 60 and _norm(title).startswith(_norm(keyword))


def _intro_ok(content: str, keyword: str) -> bool:
    m = _FIRST_P.search(content)
    intro = text_of(m.group(1)) if m else ""
    return 120 <= len(intro) <= 160 and _norm(keyword) in _norm(intro)


def _ask(prompt: str, max_tokens=150) -> str:
    try:
        return text_of(call_ai(messages=[{"role": "user", "content": prompt}], max_tokens=max_tokens)).strip('"')
    except Exception as e:
        print(f"[WARN] SEO fix request failed: {e}")
        return ""


def _fix_seo(a: Article, keyword: str) -> Article:
    """Models can't count characters: fix just the title and the opening paragraph with small
    requests instead of rewriting the whole article. The opening paragraph IS the meta
    description (the website uses the start of the content), so `meta` is taken from it."""
    for _ in range(2):
        if _title_ok(a.title, keyword):
            break
        a.title = _ask(f'Rewrite this SEO title so it STARTS with exactly "{keyword}" and is 45-60 characters '
                       f"in total. Title case, no quotes, no em dashes. Reply with only the title.\n\n{a.title}") or a.title
    for _ in range(2):
        if _intro_ok(a.content, keyword):
            break
        m = _FIRST_P.search(a.content)
        if not m:
            break
        new = _ask(f'Rewrite this opening paragraph as 1-2 sentences totalling 140-155 characters. It must contain '
                   f'the exact phrase "{keyword}" and state the value plainly. It is also the meta description. '
                   f"Plain text, no quotes, no em dashes. Reply with only the text.\n\n{text_of(m.group(1))}")
        if new:
            a.content = a.content[:m.start()] + f"<p>{html.escape(new, quote=False)}</p>" + a.content[m.end():]
    m = _FIRST_P.search(a.content)
    a.meta = text_of(m.group(1)) if m else a.meta
    a.focus_keyword = keyword
    return a


def _key_words(keyword: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", keyword.lower()) if len(w) > 2]


def _rule_checks(client, keyword: str, a: Article) -> list[str]:
    """Objective SEO/format checks. Any issue here fails the draft regardless of score."""
    issues = []
    kw = _key_words(keyword)
    if not 30 <= len(a.title) <= 60:
        issues.append(f"SEO title is {len(a.title)} characters; it must be 30-60.")
    if not _norm(a.title).startswith(_norm(keyword)):
        issues.append(f'The title must START with the focus keyword "{keyword}".')
    if "<h1" in a.content.lower():
        issues.append("Do not use an <h1> in the content; the page shows the title as the H1.")
    if not _intro_ok(a.content, keyword):
        issues.append(f'The opening paragraph must be 140-155 characters and contain "{keyword}" '
                      "(it is the page's meta description).")
    words = len(text_of(a.content).split())
    if words < client.min_words * 0.9:  # small misses are not worth a full rewrite
        issues.append(f"Article is {words} words; it must be at least {client.min_words}.")
    if client.max_words and words > client.max_words * 1.15:
        issues.append(f"Article is {words} words; cut it to at most {client.max_words}. Remove repetition and "
                      "generic background, keep the decision-useful content.")
    if a.content.count("<table") != 1:
        issues.append("Include exactly one data table.")
    if a.content.count("[IMAGE_PLACEHOLDER:") != 2:
        issues.append("Include exactly two [IMAGE_PLACEHOLDER: ...] lines (after the 2nd and 4th H2).")
    if len(faq_items(a.content)) < 5:
        issues.append('Include 5 FAQs after <h2 id="faqs">, each as <h3>question</h3><p>answer</p>.')
    site = re.sub(r"^https?://(www\.)?", "", client.brand.website).rstrip("/")
    links = set(re.findall(rf'href="https?://(?:www\.)?{re.escape(site)}(/[^"]*)"', a.content)) if site else set()
    if client.internal_links and len(links) < 2:
        issues.append("Add at least 2 different internal links from the INTERNAL LINKS list inside the body text.")
    if a.category not in client.categories:
        issues.append(f"Category must be exactly one of: {', '.join(client.categories)}.")
    found = [b for b in _BANNED if re.search(rf"\b{re.escape(b)}\b", text_of(a.content).lower())]
    if found:
        issues.append(f"Remove banned phrases: {', '.join(found)}.")
    return issues


def _ai_review(client, keyword: str, a: Article, research: str) -> tuple[int, list[str]]:
    """Senior-editor review. Returns (score 1-10, list of specific issues)."""
    prompt = f"""You are the senior technical editor for {client.brand.name}. Review this article strictly.

COMPANY KNOWLEDGE (verified facts):
{client.context or "-"}

RESEARCH BRIEF GIVEN TO THE WRITER (searches, papers, news, background):
{research or "-"}

FOCUS KEYWORD: {keyword}
SEO TITLE: {a.title}
ARTICLE:
{text_of(a.content)}

The Key Takeaways box, Contents list and FAQ section are fixed parts of the company template:
do not comment on their presence or naming.

Score 1-10 against these criteria (8+ means ready to publish on {client.brand.name}'s professional website):
1. Accuracy: any statistic, price, project, test result or standard clause not supported by the
   company knowledge or research data counts as fabricated and is a serious issue. Technically wrong
   statements are serious issues.
2. Professional tone for {client.audience}: authoritative, precise, no hype, no filler, not salesy.
3. Depth and usefulness: real expert reasoning, decision-useful, covers the topic fully.
4. SEO: matches search intent, keyword used naturally, descriptive headings, strong FAQs.
5. Structure and readability.

Return JSON: {{"score": <integer 1-10>, "issues": [<up to 8 specific, actionable fixes, quoting the problem text>]}}"""
    try:
        data = json.loads(call_ai(messages=[{"role": "user", "content": prompt}],
                                  max_tokens=2000, tier="smart", json_mode=True))
        issues = [" ".join(str(v) for v in i.values()) if isinstance(i, dict) else str(i)
                  for i in data.get("issues", [])]
        return int(data.get("score", 0)), issues[:8]
    except Exception as e:
        print(f"[WARN] Review step failed: {e}")
        return 0, []


# ── the writer ────────────────────────────────────────────────────────────────

_IMAGE_RULES = """   IMAGE RULES (header image and both placeholders):
   - Describe one concrete scene a photographer would shoot: who or what, doing what, where.
     Good: "workers tying reinforcement bars on site", "concrete bridge deck under construction",
     "engineer reviewing drawings at building site". Bad: "GFRP rebar market growth", "rebar cost comparison".
   - Use plain everyday words a stock library tags photos with. No acronyms, product codes, brand names,
     standards (IS, IRC, ASTM), numbers or abstract ideas (market, growth, cost, benefits, regulations).
   - If the product itself is too specialised to be photographed, show the setting where it is used.
   - No text, charts, diagrams, illustrations or screenshots.
   - The two placeholders show different scenes, each matching the section above it; the header image shows
     the article's main subject.
"""


def _system_prompt(client, keyword: str) -> str:
    length = (f"{client.min_words}-{client.max_words} words" if client.max_words
              else f"minimum {client.min_words} words")
    context_block = (f"\nCOMPANY KNOWLEDGE (the only source for claims about the company):\n{client.context}\n"
                     if client.context else "")
    links_block = (f"\nINTERNAL LINKS (REQUIRED: link 2-3 different pages, each once, with descriptive anchor text):\n{client.internal_links}\n"
                   if client.internal_links else "")
    notes_block = (f"\nCLIENT-SPECIFIC RULES (follow these too):\n{client.writing_notes}\n"
                   if client.writing_notes else "")
    image_block = _IMAGE_RULES + (f"   For {client.brand.name}:\n" + "".join(
        f"   {line.strip()}\n" for line in client.image_notes.strip().splitlines()) if client.image_notes else "")
    return f"""You are a senior technical content writer and SEO specialist for {client.brand.name}.
You write for {client.audience}. Voice: {client.brand.voice}
Always respond using the exact delimiter format requested — no markdown, no code fences.
The focus keyword for this article is: "{keyword}"

BRAND:
- Company: {client.brand.name} ({client.brand.website}), {client.brand.location or client.geo_label}
- Readers: {client.audience}
{context_block}{links_block}{notes_block}
WRITING STANDARDS (professional B2B / technical):
1. Write as an industry expert. Explain the "why" behind every claim with expert reasoning.
2. Accuracy first: never invent statistics, prices, project names, test results, quotes or standard
   clause numbers. Use figures only from COMPANY KNOWLEDGE or the RESEARCH BRIEF; otherwise describe
   qualitatively ("significantly lighter", "typically higher"). Name standards only as given.
   Use findings from the research papers where they strengthen the argument, referred to generally
   ("a 2024 study found..."). Never quote prices: say they depend on the requirement and point to
   a quotation or the contact page.
3. Be balanced and credible: mention genuine limitations or design considerations where relevant
   (trade-offs, constraints, cases where it is not the right choice).
4. Ground the article in {client.geo_label}: local rules and standards, conditions and
   market context.
5. Mention {client.brand.name} naturally at most 2-3 times; no sales pitch outside the conclusion.
6. Third person or "we" for the company only. No "I". Address the reader as "you" sparingly.
7. Banned: em dashes, exclamation marks, rhetorical openers, and phrases such as "in today's world",
   "fast-paced", "game-changer", "revolutionary", "unlock", "dive into", "delve", "look no further",
   "it's important to note", "in conclusion", "landscape", "elevate", "seamless".
8. Short paragraphs (2-4 sentences). Use <strong> only for genuinely key terms.
9. Length: {length}. Be concise: every paragraph must earn its place; no padding, no repeated points,
   no generic history or background the readers already know.
10. Internal links go inside substantive sentences as natural anchor text. Never write
   navigation sentences such as "see our products page" or "visit our knowledge hub".

SEO REQUIREMENTS:
1. Match search intent for the keyword (informational, comparison or commercial) and cover the topic
   more completely than competing pages.
2. Focus keyword: at the START of the title, in the opening paragraph, in at least one H2, and in the conclusion.
   Natural use only (about 0.5-1.5% density); use related terms and synonyms.
3. H2 headings must be descriptive; phrase 2-3 of them as the questions people actually search.
4. Exactly 1 data table that adds real value (specification, comparison or decision table).
5. FAQ: 5 questions people genuinely search, taken from REAL GOOGLE SEARCHES in the research brief
   wherever they fit the topic (rephrased as proper questions), each answered directly in 40-70 words;
   the first sentence answers the question.
6. Exactly 2 image placeholders, as shown in the structure, in this format:
   [IMAGE_PLACEHOLDER: 3-6 word stock photo search phrase]
   Each phrase is searched on a free stock photo library (Unsplash), so follow the IMAGE RULES below.
{image_block}
CONTENT FORMAT: clean semantic HTML only (p, h2, h3, ul, ol, li, strong, a, blockquote, table).
No <h1> (the page shows the title as the H1), no classes, no inline styles, no <style> or <div>.

STRUCTURE (choose 4-5 H2 sections that best serve the keyword; avoid generic names like
"Step-by-Step Guide" or "Common Mistakes" unless the topic truly calls for it):

<p>[Opening paragraph: 1-2 sentences, STRICTLY 140-155 characters, containing the exact focus keyword
and stating the value plainly. It is used as the page's meta description.]</p>
<p>[1-2 sentences on what the article covers.]</p>
<blockquote><strong>Key Takeaways</strong>
<ul>[4 specific, factual takeaways as <li>]</ul></blockquote>
<p><strong>Contents</strong></p>
<ul>[one <li><a href="#section-N">H2 title</a></li> per H2, then <li><a href="#faqs">FAQs</a></li>]</ul>
<h2 id="section-1">[H2]</h2>
[Section content: paragraphs, <h3> sub-sections and lists as needed. MUST include one internal link: <a href="URL from INTERNAL LINKS">descriptive anchor</a>]
<h2 id="section-2">[H2]</h2>
[Section content]
[IMAGE_PLACEHOLDER: 3-6 word stock photo search phrase]
<h2 id="section-3">[H2]</h2>
[Section content including the data table:
 <table><thead><tr><th>..</th>...</tr></thead><tbody>[4-8 rows]</tbody></table>]
<h2 id="section-4">[H2]</h2>
[Section content. MUST include one internal link: <a href="URL from INTERNAL LINKS">descriptive anchor</a> (a different page)]
[IMAGE_PLACEHOLDER: 3-6 word stock photo search phrase]
[At most 1 more H2 section (section-5) if the topic truly needs it]
<h2 id="section-conclusion">[Conclusion heading that includes the focus keyword]</h2>
[1-2 paragraphs summarising the decision-relevant points. May include one internal link: <a href="URL from INTERNAL LINKS">descriptive anchor</a>]
<h2 id="faqs">Frequently Asked Questions</h2>
[5 x <h3>[Question]</h3><p>[Answer]</p>]

Respond using EXACTLY this format (no JSON, no code fences):

===TITLE===
[SEO title 45-60 chars that STARTS with the exact focus keyword, then a colon and a benefit]
===TITLE_END===
===CATEGORY===
[ONE of: {", ".join(client.categories)}]
===CATEGORY_END===
===TAGS===
[6-8 comma-separated tags]
===TAGS_END===
===FEATURED_IMAGE===
[3-6 word stock photo search phrase for the header image, following the IMAGE RULES]
===FEATURED_IMAGE_END===
===CONTENT===
[The complete HTML, no bracketed instructions remaining except the 2 IMAGE_PLACEHOLDER lines]
===CONTENT_END==="""


def generate_blog(client, keyword: str, research: str = "") -> Article:
    """Write, check and review an article; rewrite (max 2x) until it passes. Returns the best draft."""
    # The keyword is often typed in lowercase; prompts show it cased as the sources write it ("GFRP"),
    # because the model copies the exact phrase it is given. All checks ignore case.
    keyword = cased_keyword(keyword, f"{research}\n{client.context}")
    system = _system_prompt(client, keyword)
    research_block = f"{research}\n\n" if research else ""
    recent = get_recent_blog_links(client)
    recent_block = f"RECENT POSTS (link to the most relevant 1-2):\n{recent}\n\n" if recent else ""

    best, feedback = None, ""
    for attempt in range(1, MAX_DRAFTS + 1):
        user_prompt = (f"{research_block}{recent_block}{feedback}"
                       f'Now write the complete article for the focus keyword: "{keyword}". '
                       "Follow the structure and the output format exactly.")
        print(f"[WRITE] Writing draft {attempt} of {MAX_DRAFTS}" + (" (applying editor feedback)" if feedback else ""))
        try:
            raw = call_ai(messages=[{"role": "user", "content": user_prompt}],
                          system=system, max_tokens=16000, tier="smart", cache_system=True)
        except RuntimeError as e:  # out of free quota: keep the best draft so far, if any
            if best is None:
                raise
            print(f"[REVIEW] Stopping rewrites ({e.__class__.__name__}: quota); using the best draft so far")
            break
        try:
            draft = _fix_case(_fix_seo(_fix_dashes(_parse(raw, keyword)), keyword), keyword)
        except ValueError as e:
            print(f"[REVIEW] Draft {attempt}: unusable output ({e})")
            feedback = f"EDITOR FEEDBACK: the previous reply was unusable: {e}. Use the exact format.\n\n"
            continue
        rule_issues = _rule_checks(client, keyword, draft)
        score, ai_issues = _ai_review(client, keyword, draft, research)
        issues = rule_issues + ai_issues
        passed = score >= PASS_SCORE and not rule_issues
        print(f"[REVIEW] Draft {attempt}: score {score}/10, {len(rule_issues)} rule issue(s)"
              + (" -> PASS" if passed else ""))
        for i in issues[:6]:
            print(f"         - {i[:140]}")
        rank = (not rule_issues, score)
        if best is None or rank > best[0]:
            draft.review_score, draft.review_notes = score, issues
            best = (rank, draft)
        if passed:
            break
        feedback = ("EDITOR FEEDBACK on your previous draft. Rewrite the whole article and fix every point:\n"
                    + "\n".join(f"- {i}" for i in issues) + "\n\n")
    if best is None:
        raise ValueError("No usable draft after review attempts")

    article = best[1]
    content = _style_tables(article.content)
    marker = re.search(r'<h2[^>]*id="faqs"', content)
    cta = build_cta(client)
    content = content[:marker.start()] + cta + "\n" + content[marker.start():] if marker else content + cta
    article.content = content + "\n" + faq_schema(content)
    return article
