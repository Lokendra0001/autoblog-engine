"""Scheduler, daily runs and research parsing (all offline)."""

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import cli
from agent import config, keywords, pipeline, planner, research


def _client():
    c = config.load_client("bhandari")
    c.strapi.url, c.strapi.token = "https://cms.example", "tok"
    return c


class CronTests(unittest.TestCase):
    def test_cron_entry_replaces_old_one_and_keeps_others(self):
        existing = "0 1 * * * other-job\n5 5 * * * old cli.py auto # seowriter-auto\n"
        calls = []

        def fake_run(cmd, **kw):
            calls.append((cmd, kw.get("input")))
            out = calls[-1][1] if cmd == ["crontab", "-"] else (calls[1][1] if len(calls) > 2 else existing)
            return mock.Mock(returncode=0, stdout=out or "")

        with mock.patch("subprocess.run", side_effect=fake_run):
            self.assertTrue(cli._schedule_cron("on", 3, 37))
        written = calls[1][1]
        self.assertIn("other-job", written)
        self.assertEqual(written.count("seowriter-auto"), 1)
        self.assertIn("37 3 * * * cd ", written)
        self.assertIn("cli.py auto >>", written)


class RunDueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.c = _client()
        self.c.max_news_per_month = 0  # the publish-day news check has its own tests
        patcher = mock.patch.object(type(self.c), "data_dir", new_callable=mock.PropertyMock,
                                    return_value=Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        planner.save_plan(self.c, {"month": "2026-11", "items": [
            {"date": "2026-11-24", "keyword": "gfrp rebar for bridge decks", "angle": "a", "category": "Applications",
             "status": "planned", "attempts": 0, "title": None, "draft": None}]})

    def _run(self, **preview):
        with mock.patch.object(pipeline, "preview_article", **preview):
            planner.run_due(self.c, today=date(2026, 11, 24))
        return planner.load_plan(self.c, "2026-11")["items"][0]

    def test_written_and_uploaded_as_draft(self):
        data = {"title": "T", "category": "Applications", "readTime": "7 min read",
                "review": {"score": 9, "notes": []}}
        item = self._run(return_value={"path": Path("x.html"), "title": "T", "data": data,
                                       "upload": {"result": "uploaded", "status": "draft", "documentId": "d"}})
        self.assertEqual((item["status"], item["upload"], item["draft"]), ("done", "uploaded", "x.html"))

    def test_files_destination_reports_saved(self):
        data = {"title": "T", "category": "Applications", "readTime": "7 min read", "review": {"score": 9, "notes": []}}
        item = self._run(return_value={"path": Path("20261124-t.html"), "title": "T", "data": data})
        self.assertEqual((item["status"], item["draft"]), ("done", "20261124-t.html"))
        self.assertNotIn("upload", item)

    def test_already_on_site_is_skipped(self):
        item = self._run(side_effect=pipeline.AlreadyOnSite("already there"))
        self.assertEqual((item["status"], item["last_error"]), ("skipped", "already there"))

    def test_error_is_retried_then_failed(self):
        item = self._run(side_effect=RuntimeError("quota"))
        self.assertEqual((item["status"], item["attempts"]), ("planned", 1))

    def test_pull_next_writes_the_next_article_today(self):
        with mock.patch.object(pipeline, "preview_article", side_effect=pipeline.AlreadyOnSite("x")) as p:
            planner.run_due(self.c, today=date(2026, 11, 22), pull_next=True)
        p.assert_called_once()
        self.assertEqual(planner.load_plan(self.c, "2026-11")["items"][0]["date"], "2026-11-22")

    def test_nothing_due_before_date(self):
        with mock.patch.object(pipeline, "preview_article") as p:
            planner.run_due(self.c, today=date(2026, 11, 23))
        p.assert_not_called()


class NewsTopicTests(unittest.TestCase):
    """Publish day: a relevant fresh news topic replaces the planned one; otherwise the plan stands."""

    setUp = RunDueTests.setUp

    def _run_with(self, ai_reply, site=()):
        self.c.max_news_per_month = 1
        data = {"title": "T", "category": "Industry Use", "readTime": "6 min read", "review": {"score": 9, "notes": []}}
        with mock.patch.object(planner.trends, "gather_headlines", return_value=["NHAI approves GFRP for coastal bridges"]), \
             mock.patch.object(pipeline, "site_titles", return_value=list(site)), \
             mock.patch.object(planner, "call_ai", return_value=json.dumps(ai_reply)), \
             mock.patch.object(pipeline, "preview_article", return_value={"path": Path("x.html"), "title": "T", "data": data}) as p:
            planner.run_due(self.c, today=date(2026, 11, 24))
        return p.call_args[0][1], planner.load_plan(self.c, "2026-11")["items"][0]

    def test_relevant_news_replaces_planned_topic(self):
        kw, item = self._run_with({"use_news": True, "reason": "new policy", "keyword": "GFRP rebar NHAI approval",
                                   "angle": "What the approval means", "category": "Industry Use"})
        self.assertEqual(kw, "GFRP rebar NHAI approval")
        self.assertEqual((item["planned_keyword"], item["news_checked"]), ("gfrp rebar for bridge decks", True))

    def test_monthly_news_limit_reached_skips_news_check(self):
        plan = planner.load_plan(self.c, "2026-11")
        plan["items"].insert(0, {"date": "2026-11-03", "keyword": "news one", "planned_keyword": "x", "status": "done",
                                 "category": "Trends", "angle": "", "attempts": 0, "title": "N", "draft": "n.html"})
        planner.save_plan(self.c, plan)
        with mock.patch.object(planner, "_fresh_topic") as fresh:
            kw, _ = self._run_with({"use_news": True, "keyword": "unused"})
        fresh.assert_not_called()
        self.assertEqual(kw, "gfrp rebar for bridge decks")

    def test_no_relevant_news_keeps_planned_topic(self):
        kw, item = self._run_with({"use_news": False, "reason": "nothing relevant"})
        self.assertEqual(kw, "gfrp rebar for bridge decks")
        self.assertNotIn("planned_keyword", item)

    def test_news_topic_already_covered_is_ignored(self):
        kw, _ = self._run_with({"use_news": True, "keyword": "GFRP rebar for water tanks", "category": "x"},
                                  site=["GFRP Rebar for Water Tanks: Corrosion-Free Reinforcement"])
        self.assertEqual(kw, "gfrp rebar for bridge decks")


class ResearchParsingTests(unittest.TestCase):
    def test_openalex_abstract_reconstruction(self):
        self.assertEqual(research._abstract({"Abstract:": [0], "GFRP": [1], "bars": [2], "bond": [3]}), "GFRP bars bond")
        self.assertEqual(research._abstract(None), "")

    def test_core_term(self):
        self.assertEqual(keywords.core_term("GFRP rebar design for deflection and crack control"), "gfrp rebar design")

    def test_suggest_parses_response(self):
        resp = mock.Mock(text=json.dumps(["gfrp", ["gfrp rebar", "gfrp rebar price"], [], {}]))
        resp.raise_for_status = mock.Mock()
        with mock.patch.object(keywords.requests, "get", return_value=resp), mock.patch.object(keywords.time, "sleep"):
            self.assertEqual(keywords.suggest("gfrp", _client()), ["gfrp rebar", "gfrp rebar price"])


if __name__ == "__main__":
    unittest.main()
