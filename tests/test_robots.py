"""Unit tests for RobotsHandler (no live network required for core logic)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from webvac.utils.robots import RobotsHandler


class TestRobotsHandlerOffline(unittest.IsolatedAsyncioTestCase):
    async def test_404_allows_all(self):
        handler = RobotsHandler(user_agent="*")

        def fake_download(_url: str):
            return 404, b""

        with patch.object(handler, "_download_robots", side_effect=fake_download):
            await handler.fetch("https://www.spacex.com/")
        self.assertTrue(handler.is_allowed("https://www.spacex.com/"))
        self.assertTrue(handler.is_allowed("https://www.spacex.com/launches/"))

    async def test_python_default_ua_403_would_block_but_we_use_browser_ua(self):
        """Regression: bare urllib UA got 403 → robotparser disallow_all."""
        handler = RobotsHandler(user_agent="*")
        self.assertIn("Mozilla", handler.fetch_user_agent)

        def fake_download(_url: str):
            # Simulate CDN 404 for browser UA (SpaceX case) → allow
            return 404, b"Not Found"

        with patch.object(handler, "_download_robots", side_effect=fake_download):
            await handler.fetch("https://www.spacex.com/")
        self.assertTrue(handler.is_allowed("https://www.spacex.com/"))

    async def test_real_disallow_honoured(self):
        handler = RobotsHandler(user_agent="*")
        body = b"User-agent: *\nDisallow: /private\nAllow: /\n"

        def fake_download(_url: str):
            return 200, body

        with patch.object(handler, "_download_robots", side_effect=fake_download):
            await handler.fetch("https://example.com/")
        self.assertTrue(handler.is_allowed("https://example.com/"))
        self.assertFalse(handler.is_allowed("https://example.com/private/secret"))

    async def test_respect_robots_false(self):
        handler = RobotsHandler(respect_robots=False)
        self.assertTrue(handler.is_allowed("https://example.com/anything"))


if __name__ == "__main__":
    unittest.main()
