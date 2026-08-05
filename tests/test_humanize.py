"""Unit tests for humanize path math and config."""

from __future__ import annotations

import unittest

from webvac.utils.humanize import (
    bezier_point,
    build_bezier_path,
    config_from_mapping,
    ease_in_out_cubic,
)
from webvac.utils.browser import BrowserManager


class TestHumanizeMath(unittest.TestCase):
    def test_bezier_endpoints(self):
        p0, p3 = (0.0, 0.0), (100.0, 50.0)
        p1, p2 = (20.0, 80.0), (80.0, -10.0)
        self.assertEqual(bezier_point(0.0, p0, p1, p2, p3), p0)
        end = bezier_point(1.0, p0, p1, p2, p3)
        self.assertAlmostEqual(end[0], 100.0)
        self.assertAlmostEqual(end[1], 50.0)

    def test_ease_bounds(self):
        self.assertEqual(ease_in_out_cubic(0.0), 0.0)
        self.assertEqual(ease_in_out_cubic(1.0), 1.0)
        mid = ease_in_out_cubic(0.5)
        self.assertGreater(mid, 0.4)
        self.assertLess(mid, 0.6)

    def test_path_reaches_target(self):
        path = build_bezier_path((10, 10), (400, 300), steps=16, jitter=0, overshoot=False)
        self.assertGreaterEqual(len(path), 16)
        self.assertAlmostEqual(path[-1][0], 400.0, places=5)
        self.assertAlmostEqual(path[-1][1], 300.0, places=5)

    def test_overshoot_still_ends_on_target(self):
        path = build_bezier_path((0, 0), (200, 0), steps=12, jitter=0, overshoot=True)
        self.assertAlmostEqual(path[-1][0], 200.0, places=5)
        self.assertAlmostEqual(path[-1][1], 0.0, places=5)

    def test_config_from_mapping(self):
        cfg = config_from_mapping({"humanize": False, "humanize_idle_min": 0.1})
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.idle_min, 0.1)


class TestSecChUa(unittest.TestCase):
    def test_sec_ch_matches_chrome_major(self):
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
        )
        ch = BrowserManager._sec_ch_ua_for_ua(ua)
        self.assertIn('v="133"', ch)
        self.assertIn("Google Chrome", ch)

    def test_edge_brand(self):
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0"
        )
        ch = BrowserManager._sec_ch_ua_for_ua(ua)
        self.assertIn("Microsoft Edge", ch)


if __name__ == "__main__":
    unittest.main()
