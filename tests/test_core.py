"""Offline tests for the parts that need no AI or network: python -m unittest discover tests"""

import json
import re
import unittest
from datetime import date

from agent import config, pipeline, planner, writer

KEYWORD = "GFRP rebar for bridges"


def _client(**overrides):
    c = config.load_client("bhandari")
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


def _good_content(words=1700):
    filler = " ".join(["GFRP reinforcement resists chloride corrosion in coastal concrete decks."] * (words // 8))
    faqs = "".join(f"<h3>Question {i}?</h3><p>Answer {i} explains the point directly.</p>" for i in range(5))
    return (f"<p>{KEYWORD.capitalize()} offers corrosion-free reinforcement for decks and piers, "
            "cutting maintenance over the design life of coastal structures.</p>"
            "<h2 id=\"section-1\">Why corrosion matters</h2><p>" + filler + " See our "
            "<a href=\"https://www.bhandaritechfab.com/our-products\">GFRP products</a> and "
            "<a href=\"https://www.bhandaritechfab.com/certificates\">test reports</a>.</p>"
            "[IMAGE_PLACEHOLDER: concrete bridge construction site]"
            "<table><thead><tr><th>Property</th><th>GFRP</th></tr></thead><tbody><tr><td>Weight</td>"
            "<td>Lighter</td></tr></tbody></table>"
            "[IMAGE_PLACEHOLDER: rebar cage on site]"
            f"<h2 id=\"faqs\">Frequently Asked Questions</h2>{faqs}")


def _good_article(**overrides):
    a = writer.Article(title="GFRP Rebar for Bridges: A Practical Engineering Guide",
                       meta="x" * 150, focus_keyword=KEYWORD, category="Applications",
                       tags=["GFRP"], featured_query="bridge", content=_good_content())
    for k, v in overrides.items():
        setattr(a, k, v)
    return a


class ScheduleTests(unittest.TestCase):
    def test_full_month_spreads_evenly_on_allowed_weekdays(self):
        c = _client(posts_per_month=8, publish_weekdays=[1, 4])
        dates = planner._schedule_dates(c, date(2026, 11, 1))
        self.assertEqual(len(dates), 8)
        self.assertEqual(dates, sorted(set(dates)))
        self.assertTrue(all(d.weekday() in (1, 4) and d.month == 11 for d in dates))

    def test_mid_month_is_prorated(self):
        c = _client(posts_per_month=8, publish_weekdays=[1, 4])
        self.assertEqual(planner._schedule_dates(c, date(2026, 11, 21)), [date(2026, 11, 24), date(2026, 11, 27)])

    def test_four_a_month_is_not_bunched(self):
        c = _client(posts_per_month=4, publish_weekdays=[1, 4])
        dates = planner._schedule_dates(c, date(2026, 11, 1))
        self.assertEqual(len(dates), 4)
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        self.assertTrue(all(g >= 6 for g in gaps), gaps)

    def test_no_dates_left(self):
        self.assertEqual(planner._schedule_dates(_client(publish_weekdays=[1]), date(2026, 11, 30)), [])


class ParseTests(unittest.TestCase):
    RAW = ("===TITLE===\nA Title\n===TITLE_END===\n===META===\nA meta\n===META_END===\n"
           "===CATEGORY===\nEducation\n===CATEGORY_END===\n===TAGS===\na, b ,c\n===TAGS_END===\n"
           "===CONTENT===\n<p>Body</p>\n===CONTENT_END===")

    def test_parses_all_sections(self):
        a = writer._parse(self.RAW, "kw")
        self.assertEqual((a.title, a.meta, a.category, a.tags, a.content),
                         ("A Title", "A meta", "Education", ["a", "b", "c"], "<p>Body</p>"))
        self.assertEqual((a.focus_keyword, a.featured_query), ("kw", "kw"))  # fallbacks

    def test_tolerates_missing_end_marker(self):
        a = writer._parse(self.RAW.replace("\n===CONTENT_END===", ""), "kw")
        self.assertEqual(a.content, "<p>Body</p>")

    def test_missing_required_section_raises(self):
        with self.assertRaises(ValueError):
            writer._parse(self.RAW.replace("===TITLE===", "TITLE:"), "kw")

    def test_dashes_replaced(self):
        a = writer._fix_dashes(writer.Article("A — B", "m", "k", "c", content="x — y"))
        self.assertEqual((a.title, a.content), ("A, B", "x, y"))


class RuleCheckTests(unittest.TestCase):
    def setUp(self):
        self.c = _client(min_words=1500, max_words=2000)

    def test_good_article_passes(self):
        self.assertEqual(writer._rule_checks(self.c, KEYWORD, _good_article()), [])

    def test_failures_are_reported(self):
        bad = _good_article(title="Short", category="Nope",
                            content="<h1>X</h1>" + _good_content().replace("<table", "<p").replace(KEYWORD.capitalize(), "It")
                            .replace("bhandaritechfab.com", "example.com"))
        issues = " ".join(writer._rule_checks(self.c, KEYWORD, bad))
        for expected in ("internal links", "30-60", "START", "<h1>", "opening paragraph", "table", "Category"):
            self.assertIn(expected, issues)

    def test_too_long_is_reported(self):
        issues = writer._rule_checks(self.c, KEYWORD, _good_article(content=_good_content(words=2400)))
        self.assertTrue(any("cut it" in i for i in issues), issues)

    def test_title_must_start_with_keyword(self):
        self.assertTrue(writer._title_ok("GFRP Rebar for Bridges: A Practical Engineering Guide", KEYWORD))
        self.assertFalse(writer._title_ok("A Practical Guide to GFRP Rebar for Bridges in India", KEYWORD))

    def test_fix_seo_repairs_title_and_intro_and_derives_meta(self):
        good_intro = f"{KEYWORD} cuts corrosion repairs in coastal decks and piers, so owners spend less over the design life of the structure."
        answers = iter(["GFRP Rebar for Bridges: Corrosion-Free Reinforcement", good_intro])
        orig, writer._ask = writer._ask, lambda *a, **k: next(answers)
        try:
            a = writer._fix_seo(_good_article(title="Why Bridges Need Better Rebar",
                                              content="<p>Too short.</p><p>Second.</p>"), KEYWORD)
        finally:
            writer._ask = orig
        self.assertTrue(writer._title_ok(a.title, KEYWORD))
        self.assertEqual(a.meta, good_intro)
        self.assertTrue(a.content.startswith(f"<p>{good_intro}</p><p>Second.</p>"))

    def test_banned_phrases_use_word_boundaries(self):
        ok = _good_article(content=_good_content().replace("Answer 1", "An elevated deck"))
        self.assertEqual(writer._rule_checks(self.c, KEYWORD, ok), [])
        bad = _good_article(content=_good_content().replace("Answer 1", "Let us delve"))
        self.assertTrue(any("delve" in i for i in writer._rule_checks(self.c, KEYWORD, bad)))


class ImageMatchTests(unittest.TestCase):
    def test_prefers_photo_matching_query_words(self):
        from agent import images
        dock = {"alt_description": "people walking on brown wooden dock", "tags": []}
        tank = {"alt_description": "concrete water tank", "tags": [{"title": "construction"}]}
        self.assertGreater(images._match("concrete water tank construction site", tank),
                           images._match("concrete water tank construction site", dock))


class HtmlTests(unittest.TestCase):
    def test_faq_items_and_schema(self):
        content = _good_content()
        self.assertEqual(len(writer.faq_items(content)), 5)
        schema = json.loads(re.search(r">(.*)</script>", writer.faq_schema(content)).group(1))
        self.assertEqual(schema["@type"], "FAQPage")
        self.assertEqual(schema["mainEntity"][0]["name"], "Question 0?")
        self.assertEqual(writer.faq_schema("<p>none</p>"), "")

    def test_tables_get_inline_styles(self):
        out = writer._style_tables("<table><tr><th>a</th><td>b</td></tr></table>")
        self.assertIn("overflow-x:auto", out)
        self.assertIn('<th style=', out)
        self.assertIn('<td style=', out)

    def test_slug_and_read_time(self):
        self.assertEqual(pipeline.slugify("GFRP vs Steel: Cost (2026)!"), "gfrp-vs-steel-cost-2026")
        self.assertEqual(pipeline.read_time("<p>" + "word " * 1000 + "</p><script>ignored " * 50 + "</script>"),
                         "5 min read")

    def test_fill_images(self):
        out = pipeline._fill_images("a [IMAGE_PLACEHOLDER: one] b [IMAGE_PLACEHOLDER: two] [IMAGE_PLACEHOLDER: 3]",
                                    lambda q: (f"https://img/{q}", "credit") if q != "two" else (None, None),
                                    "gfrp rebar")
        self.assertIn('alt="One, gfrp rebar"', out)
        self.assertIn('src="https://img/one"', out)
        self.assertNotIn("IMAGE_PLACEHOLDER", out)
        self.assertEqual(out.count("<figure"), 1)

    def test_preview_embeds_data_safely(self):
        data = {"title": "T", "slug": "t", "category": "Education", "readTime": "1 min read",
                "date": "2026-11-24", "image": "", "imageSource": "",
                "content": '<p>x</p><script type="application/ld+json">{}</script>',
                "meta_description": "m", "focus_keyword": "k"}
        page = pipeline.preview_page(_client(), data)
        payload = re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S).group(1)
        self.assertEqual(json.loads(payload)["content"], data["content"])


if __name__ == "__main__":
    unittest.main()
