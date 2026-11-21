"""Scheduler, notifications, daily-run events and research parsing (all offline)."""

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import cli
from agent import config, keywords, notify, pipeline, planner, research


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


class NotifyTests(unittest.TestCase):
    def _report(self, events):
        with mock.patch.object(notify, "send") as send:
            notify.run_report(_client(), events)
        return send.call_args[0] if send.called else None

    def test_subject_priorities(self):
        draft = {"kind": "draft", "title": "GFRP Rebar for Decks", "keyword": "k", "category": "Applications",
                 "read_time": "7 min read", "score": 9, "notes": [], "document_id": "d1"}
        subject, body = self._report([draft])
        self.assertIn("Draft ready for review: GFRP Rebar for Decks", subject)
        self.assertIn("/admin/content-manager/collection-types/api::blog.blog/d1", body)
        subject, _ = self._report([draft, {"kind": "failed", "keyword": "x", "attempt": 3, "max": 3, "error": "e"}])
        self.assertIn("Action needed", subject)

    def test_nothing_happened_sends_nothing(self):
        self.assertIsNone(self._report([]))


class RunDueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.c = _client()
        patcher = mock.patch.object(type(self.c), "data_dir", new_callable=mock.PropertyMock,
                                    return_value=Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        planner.save_plan(self.c, {"month": "2026-11", "items": [
            {"date": "2026-11-24", "keyword": "gfrp rebar for bridge decks", "angle": "a", "category": "Applications",
             "status": "planned", "attempts": 0, "title": None, "draft": None}]})

    def _run(self, **preview):
        with mock.patch.object(pipeline, "preview_article", **preview), \
             mock.patch.object(notify, "run_report") as report:
            planner.run_due(self.c, today=date(2026, 11, 24))
        return planner.load_plan(self.c, "2026-11")["items"][0], report.call_args[0][1]

    def test_written_and_uploaded_as_draft(self):
        data = {"title": "T", "category": "Applications", "readTime": "7 min read",
                "review": {"score": 9, "notes": []}}
        item, events = self._run(return_value={"path": Path("x.html"), "title": "T", "data": data,
                                               "upload": {"result": "uploaded", "status": "draft", "documentId": "d"}})
        self.assertEqual((item["status"], item["upload"]), ("done", "uploaded"))
        self.assertEqual(events[0]["kind"], "draft")

    def test_files_destination_reports_saved(self):
        data = {"title": "T", "category": "Applications", "readTime": "7 min read", "review": {"score": 9, "notes": []}}
        item, events = self._run(return_value={"path": Path("20261124-t.html"), "title": "T", "data": data})
        self.assertEqual(item["status"], "done")
        self.assertNotIn("upload", item)
        self.assertEqual((events[0]["kind"], events[0]["file"]), ("saved", "20261124-t.html"))

    def test_already_on_site_is_skipped(self):
        item, events = self._run(side_effect=pipeline.AlreadyOnSite("already there"))
        self.assertEqual(item["status"], "skipped")
        self.assertEqual(events[0]["kind"], "skipped")

    def test_error_is_retried_then_failed(self):
        item, events = self._run(side_effect=RuntimeError("quota"))
        self.assertEqual((item["status"], item["attempts"], events[0]["kind"]), ("planned", 1, "retry"))

    def test_nothing_due_before_date(self):
        with mock.patch.object(pipeline, "preview_article") as p, mock.patch.object(notify, "run_report"):
            planner.run_due(self.c, today=date(2026, 11, 23))
        p.assert_not_called()


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
