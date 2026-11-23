"""Where articles go: strapi / wordpress / files, and the WordPress upload of a saved article."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent import config, pipeline, publisher


def _client(**env):
    with mock.patch.dict(os.environ, {"PUBLISH_TO": "", "PUBLISH_STATUS": "", **env}):
        return config.load_client("bhandari")


class DestinationTests(unittest.TestCase):
    def test_auto_detects_configured_cms(self):
        c = _client()
        c.publish_to = ""  # auto-detect
        c.strapi.url, c.strapi.token = "https://cms.example", "tok"
        self.assertEqual(c.destination, "strapi")
        c.strapi.token = ""
        self.assertEqual(c.destination, "files")
        c.wordpress.site_url, c.wordpress.app_password = "https://wp.example", "pw"
        self.assertEqual(c.destination, "wordpress")

    def test_env_forces_files_even_with_strapi(self):
        c = _client(PUBLISH_TO="files")
        c.strapi.url, c.strapi.token = "https://cms.example", "tok"
        self.assertEqual(c.destination, "files")

    def test_publish_status_env_overrides_both_cms(self):
        c = _client(PUBLISH_TO="strapi", PUBLISH_STATUS="published")
        self.assertEqual((c.strapi.status, c.wordpress.status, c.publish_status), ("published", "publish", "published"))
        c = _client(PUBLISH_TO="wordpress", PUBLISH_STATUS="draft")
        self.assertEqual((c.wordpress.status, c.publish_status), ("draft", "draft"))
        self.assertEqual(_client(PUBLISH_TO="files").publish_status, "")

    def test_dashboard_setting_overrides_env_and_reaches_the_scheduler(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(config, "DATA_DIR", Path(tmp)):
            c = _client(PUBLISH_TO="strapi", PUBLISH_STATUS="draft")
            config.save_publish_status(c, "published")
            self.assertEqual(c.publish_status, "published")  # the running web server sees it at once
            fresh = _client(PUBLISH_TO="strapi", PUBLISH_STATUS="draft")  # what the next scheduled run loads
            self.assertEqual((fresh.publish_status, fresh.publish_status_default), ("published", "draft"))
            config.save_publish_status(fresh, "draft")  # back to the .env value: override removed
            self.assertNotIn("publish_status", config.load_settings("bhandari"))
            self.assertEqual(_client(PUBLISH_TO="strapi", PUBLISH_STATUS="published").publish_status, "published")

    def test_invalid_publish_status_fails_clearly(self):
        with self.assertRaises(ValueError):
            _client(PUBLISH_STATUS="live")

    def test_invalid_destination_fails_clearly(self):
        with self.assertRaises(ValueError):
            _client(PUBLISH_TO="medium")



class WordPressUploadTests(unittest.TestCase):
    def test_saved_article_goes_to_wordpress_as_draft(self):
        c = _client(PUBLISH_TO="wordpress")
        c.wordpress.site_url, c.wordpress.status = "https://wp.example", "draft"
        data = {"title": "T", "slug": "t", "category": "Applications", "content": "<p>x</p>",
                "meta_description": "m", "focus_keyword": "k", "tags": ["a"], "image": "", "imageFile": ""}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.html"
            path.with_suffix(".json").write_text(__import__("json").dumps(data))
            with mock.patch.object(publisher, "publish_post", return_value=(42, "https://wp.example/?p=42")) as pub, \
                 mock.patch.object(publisher, "patch_content"), mock.patch.object(pipeline.indexer, "ping_all") as ping:
                res = pipeline.upload_saved(c, path)
        self.assertEqual((res["result"], res["status"], res["documentId"], res["to"]),
                         ("uploaded", "draft", "42", "wordpress"))
        self.assertEqual(pub.call_args.kwargs["status"], "draft")
        ping.assert_not_called()  # drafts are not pinged to search engines


if __name__ == "__main__":
    unittest.main()
