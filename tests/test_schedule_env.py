"""POSTS_PER_MONTH / PUBLISH_DAYS env overrides."""

import os
import unittest
from unittest import mock

from agent import config


class ScheduleEnvTests(unittest.TestCase):
    def test_env_overrides_config(self):
        with mock.patch.dict(os.environ, {"POSTS_PER_MONTH": "4", "PUBLISH_DAYS": "Mon, wednesday,fri"}):
            c = config.load_client("bhandari")
        self.assertEqual((c.posts_per_month, c.publish_weekdays), (4, [0, 2, 4]))

    def test_unset_keeps_config(self):
        with mock.patch.dict(os.environ, {"POSTS_PER_MONTH": "", "PUBLISH_DAYS": ""}):
            c = config.load_client("bhandari")
        self.assertEqual((c.posts_per_month, c.publish_weekdays), (8, [1, 4]))

    def test_bad_values_fail_clearly(self):
        for env in ({"POSTS_PER_MONTH": "lots"}, {"PUBLISH_DAYS": "tue,funday"}):
            with mock.patch.dict(os.environ, env), self.assertRaises(ValueError):
                config.load_client("bhandari")


if __name__ == "__main__":
    unittest.main()
