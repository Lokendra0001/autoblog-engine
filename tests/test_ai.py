"""Model fallback logic in agent/ai.py, with the Gemini client mocked."""

import unittest
from unittest import mock

from google.genai import errors

from agent import ai


def _err(code, msg="x"):
    return errors.APIError(code, {"error": {"code": code, "message": msg, "status": "X"}})


class FallbackTests(unittest.TestCase):
    def setUp(self):
        ai._skipped.clear(); ai._busy_until.clear(); ai._no_thinking_cfg.clear()
        self.models = mock.patch.object(ai, "MODELS", ["a", "b"]); self.models.start()
        self.sleep = mock.patch.object(ai.time, "sleep"); self.sleep.start()
        self.addCleanup(self.models.stop); self.addCleanup(self.sleep.stop)

    def _call(self, behaviour):
        calls = []
        def gen(model, **_):
            calls.append(model)
            r = behaviour(model, len(calls))
            if isinstance(r, Exception):
                raise r
            return mock.Mock(text=r)
        with mock.patch.object(ai, "_gemini") as g:
            g.models.generate_content.side_effect = gen
            return ai.call_ai([{"role": "user", "content": "hi"}]), calls

    def test_unavailable_model_is_skipped(self):
        out, calls = self._call(lambda m, n: _err(404) if m == "a" else "OK")
        self.assertEqual((out, calls), ("OK", ["a", "b"]))
        self.assertEqual(ai._skipped, {"a": "unavailable"})

    def test_busy_model_goes_to_back_of_queue(self):
        out, calls = self._call(lambda m, n: _err(503) if m == "a" else "OK")
        self.assertEqual(calls, ["a", "a", "b"])  # one retry, then next model
        _, calls = self._call(lambda m, n: "OK")
        self.assertEqual(calls, ["b"])  # recently busy "a" is now tried last

    def test_daily_quota_raises_when_all_exhausted(self):
        with self.assertRaises(RuntimeError) as ctx:
            self._call(lambda m, n: _err(429, "GenerateRequestsPerDayPerProjectPerModel-FreeTier"))
        self.assertIn("quota", str(ctx.exception))

    def test_fatal_error_raises(self):
        with self.assertRaises(errors.APIError):
            self._call(lambda m, n: _err(400, "API key not valid"))


if __name__ == "__main__":
    unittest.main()
