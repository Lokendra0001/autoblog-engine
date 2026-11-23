"""Duplicate protection and Strapi upload, with HTTP mocked (never touches the live site)."""

import unittest
from unittest import mock

from agent import config, pipeline, strapi
from agent.state import ClientState

EXISTING = [{"title": "GFRP Rebar for Water Tanks: Corrosion-Free Reinforcement",
             "slug": "gfrp-rebar-for-water-tanks-corrosion-free-reinforcement", "documentId": "d1", "status": "draft"}]
ARTICLE = {"title": "GFRP Rebar for Bridge Decks: A Practical Guide", "slug": "gfrp-rebar-for-bridge-decks-a-practical-guide",
           "category": "Applications", "readTime": "7 min read", "date": "2026-11-24", "imageSource": "Photo by X",
           "content": "<p>x</p>", "focus_keyword": "GFRP rebar for bridge decks"}


def _client():
    c = config.load_client("bhandari")
    c.strapi.url, c.strapi.token, c.strapi.status = "https://cms.example", "tok", "draft"
    return c


def _resp(status=200, payload=None):
    r = mock.Mock(status_code=status, text=str(payload))
    r.json.return_value = payload
    r.raise_for_status = mock.Mock(side_effect=None if status < 400 else Exception(f"HTTP {status}"))
    return r


class SimilarityTests(unittest.TestCase):
    def test_same_and_different_topics(self):
        s = ClientState.similar
        self.assertTrue(s("GFRP rebar for water tanks", EXISTING[0]["title"]))
        self.assertTrue(s("GFRP rebar design for deflection and crack control",
                          "Designing GFRP Rebar for Deflection and Crack Control in Slabs"))
        self.assertFalse(s("GFRP rebar for bridge decks", EXISTING[0]["title"]))
        self.assertFalse(s("GFRP rebar", "GFRP Rebar for Bridge Decks"))

    def test_find_existing_by_slug_title_or_keyword(self):
        self.assertIsNotNone(strapi.find_existing(EXISTING, slug=EXISTING[0]["slug"]))
        self.assertIsNotNone(strapi.find_existing(EXISTING, keyword="gfrp rebar for water tanks"))
        self.assertIsNone(strapi.find_existing(EXISTING, title=ARTICLE["title"], slug=ARTICLE["slug"],
                                               keyword=ARTICLE["focus_keyword"]))


class UploadTests(unittest.TestCase):
    def test_existing_topic_is_not_uploaded(self):
        dup = dict(ARTICLE, title="GFRP Rebar for Water Tanks: A Design Guide", slug="other",
                   focus_keyword="GFRP rebar for water tanks")
        with mock.patch.object(strapi, "list_blogs", return_value=EXISTING), \
             mock.patch.object(strapi.requests, "post") as post:
            res = strapi.upload_article(_client(), dup, None)
        self.assertEqual(res["result"], "exists")
        post.assert_not_called()

    def test_own_post_without_cover_gets_cover(self):
        own = [dict(EXISTING[0], slug=ARTICLE["slug"], has_image=False)]
        with mock.patch.object(strapi, "list_blogs", return_value=own), \
             mock.patch.object(strapi, "set_cover", return_value=True) as cover, \
             mock.patch.object(strapi.requests, "post") as post, \
             mock.patch.object(strapi.Path, "is_file", return_value=True):
            res = strapi.upload_article(_client(), ARTICLE, strapi.Path("cover.jpg"))
        self.assertEqual((res["result"], res["cover_added"]), ("exists", True))
        cover.assert_called_once()
        post.assert_not_called()  # no second blog created

    def test_unreadable_blog_list_blocks_upload(self):
        with mock.patch.object(strapi, "list_blogs", return_value=None), \
             mock.patch.object(strapi.requests, "post") as post:
            self.assertEqual(strapi.upload_article(_client(), ARTICLE, None)["result"], "failed")
        post.assert_not_called()

    def test_status_override_publishes_one_article(self):
        with mock.patch.object(strapi, "list_blogs", return_value=EXISTING), \
             mock.patch.object(strapi.requests, "post",
                               return_value=_resp(201, {"data": {"documentId": "new2"}})) as post:
            res = strapi.upload_article(_client(), ARTICLE, None, status="published")
        self.assertEqual(res["status"], "published")
        self.assertEqual(post.call_args[1]["params"], {"status": "published"})

    def test_new_article_is_created_as_draft(self):
        with mock.patch.object(strapi, "list_blogs", return_value=EXISTING), \
             mock.patch.object(strapi.requests, "post",
                               return_value=_resp(201, {"data": {"documentId": "new1"}})) as post:
            res = strapi.upload_article(_client(), ARTICLE, None)
        self.assertEqual((res["result"], res["documentId"], res["status"]), ("uploaded", "new1", "draft"))
        _, kwargs = post.call_args
        self.assertEqual(kwargs["params"], {"status": "draft"})
        self.assertEqual(set(kwargs["json"]["data"]),
                         {"title", "slug", "category", "readTime", "date", "imageSource", "content"})

    def test_custom_collection_and_field_names(self):
        c = _client()
        c.strapi.collection = "articles"
        c.strapi.fields = {"title": "name", "content": "body", "readTime": "", "imageSource": "",
                           "meta_description": "seoDescription"}
        art = dict(ARTICLE, meta_description="Short summary.")
        with mock.patch.object(strapi, "list_blogs", return_value=[]), \
             mock.patch.object(strapi.requests, "post",
                               return_value=_resp(201, {"data": {"documentId": "n"}})) as post:
            strapi.upload_article(c, art, None)
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://cms.example/api/articles")
        self.assertEqual(kwargs["json"]["data"], {"name": art["title"], "slug": art["slug"], "body": "<p>x</p>",
                                                  "category": "Applications", "date": "2026-11-24",
                                                  "seoDescription": "Short summary."})

    def test_list_blogs_merges_published_and_drafts(self):
        pub = {"data": [{"documentId": "a", "title": "A", "slug": "a"}], "meta": {"pagination": {"pageCount": 1}}}
        drafts = {"data": [{"documentId": "a", "title": "A", "slug": "a"}, {"documentId": "b", "title": "B", "slug": "b"}],
                  "meta": {"pagination": {"pageCount": 1}}}
        with mock.patch.object(strapi.requests, "get", side_effect=[_resp(200, pub), _resp(200, drafts)]):
            blogs = strapi.list_blogs(_client())
        self.assertEqual([(b["documentId"], b["status"]) for b in blogs], [("a", "published"), ("b", "draft")])

    def test_list_blogs_failure_returns_none(self):
        with mock.patch.object(strapi.requests, "get", return_value=_resp(500, {})):
            self.assertIsNone(strapi.list_blogs(_client()))


class PipelineTests(unittest.TestCase):
    def test_topic_on_site_is_skipped_before_any_ai_call(self):
        with mock.patch.object(strapi, "list_blogs", return_value=EXISTING), \
             mock.patch.object(pipeline.research_mod, "research_topic") as research, \
             mock.patch.object(pipeline.writer, "generate_blog") as write:
            with self.assertRaises(pipeline.AlreadyOnSite):
                pipeline.preview_article(_client(), "GFRP rebar for water tanks")
        research.assert_not_called()
        write.assert_not_called()



class PublishDraftTests(unittest.TestCase):
    """Dashboard "Publish" button: only our own drafts, never twice."""

    def setUp(self):
        import json, tempfile
        from pathlib import Path
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c = _client()
        self.c.publish_to = "strapi"
        p = mock.patch.object(type(self.c), "drafts_dir", new_callable=mock.PropertyMock, return_value=Path(self.tmp.name))
        p.start(); self.addCleanup(p.stop)
        self.json = json
        self._save("a.html", {"result": "uploaded", "documentId": "doc1", "status": "draft"})
        self._save("b.html", {"result": "exists", "documentId": "other", "status": "draft"})

    def _save(self, name, upload):
        from pathlib import Path
        (Path(self.tmp.name) / name).with_suffix(".json").write_text(self.json.dumps(
            {**ARTICLE, "upload": upload}), encoding="utf-8")

    def test_publishes_our_draft_and_records_it(self):
        with mock.patch.object(strapi, "status_of", return_value="draft"), \
             mock.patch.object(strapi.requests, "put", return_value=_resp(200, {"data": {}})) as put, \
             mock.patch.object(pipeline, "_went_live") as live:
            res = pipeline.publish_saved(self.c, "a.html")
        self.assertEqual(res["result"], "published")
        self.assertEqual(put.call_args[1]["params"], {"status": "published"})
        self.assertIn("/doc1", put.call_args[0][0])
        live.assert_called_once()
        self.assertEqual(pipeline.uploaded_draft(self.c, "a.html")["status"], "published")
        self.assertEqual(pipeline.publish_saved(self.c, "a.html")["reason"], "already published")

    def test_already_published_in_admin_is_not_published_again(self):
        with mock.patch.object(strapi, "status_of", return_value="published"), \
             mock.patch.object(strapi.requests, "put") as put, mock.patch.object(pipeline, "_went_live"):
            self.assertEqual(pipeline.publish_saved(self.c, "a.html")["result"], "published")
        put.assert_not_called()

    def test_refuses_documents_that_are_not_our_upload(self):
        self.assertIsNone(pipeline.uploaded_draft(self.c, "b.html"))  # topic was already on the site
        self.assertIsNone(pipeline.uploaded_draft(self.c, "../a.html"))
        with mock.patch.object(strapi.requests, "put") as put:
            self.assertEqual(pipeline.publish_saved(self.c, "b.html")["result"], "failed")
        put.assert_not_called()

    def test_strapi_error_is_reported(self):
        with mock.patch.object(strapi, "status_of", return_value="draft"), \
             mock.patch.object(strapi.requests, "put", return_value=_resp(403, "forbidden")):
            res = pipeline.publish_saved(self.c, "a.html")
        self.assertEqual(res["result"], "failed")
        self.assertIn("update", res["reason"])
        self.assertEqual(pipeline.uploaded_draft(self.c, "a.html")["status"], "draft")


if __name__ == "__main__":
    unittest.main()
