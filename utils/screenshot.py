"""
screenshot.py — CAPTCHA-page screenshot module.

Captures a full-page screenshot ONLY when a bot-block / CAPTCHA page is
detected — not on every page. Screenshots are saved as PNG files under
<output_dir>/screenshots/.

Usage::

    module = ScreenshotModule(output_dir="scraped_data")
    path = await module.capture_if_blocked(page, url)
    # path is a relative string like "scraped_data/screenshots/example_com_20260603_123456.png"
    # or None if the page was not blocked.
"""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import Optional

from utils.detection import is_bot_detected


class ScreenshotModule:
    """
    Takes a screenshot of blocked / CAPTCHA pages only.

    Attributes:
        output_dir:      Root output directory (e.g. ``"scraped_data"``).
        screenshots_dir: Subdirectory name (default: ``"screenshots"``).
        full_page:       Capture full scrollable page (default: True).
    """

    def __init__(
        self,
        output_dir: str = "scraped_data",
        screenshots_subdir: str = "screenshots",
        full_page: bool = True,
    ) -> None:
        self.output_dir = output_dir
        self.screenshots_subdir = screenshots_subdir
        self.full_page = full_page
        self._screenshots_path = os.path.join(output_dir, screenshots_subdir)

    # ── Public API ────────────────────────────────────────────────────────────

    async def capture_if_blocked(
        self,
        page,
        url: str,
        response=None,
    ) -> Optional[str]:
        """
        Detect whether the page is a CAPTCHA / bot-block page.
        If yes, capture a full-page screenshot and return the file path.
        If no, return None.

        Args:
            page:     A Playwright/Patchright ``Page`` object (already loaded).
            url:      The original requested URL (used for filename generation).
            response: The ``Response`` from ``page.goto()``, or None.

        Returns:
            Relative file path string if a screenshot was saved, else None.
        """
        try:
            blocked = await is_bot_detected(page, response)
        except Exception:
            blocked = False

        if not blocked:
            return None

        return await self._capture(page, url)

    async def capture_forced(self, page, url: str) -> Optional[str]:
        """
        Unconditionally capture a screenshot regardless of detection.
        Useful for debugging / manual invocation.
        """
        return await self._capture(page, url)

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _capture(self, page, url: str) -> Optional[str]:
        """
        Internal: ensure directory exists, build filename, take screenshot.
        """
        try:
            os.makedirs(self._screenshots_path, exist_ok=True)
            filename = self._build_filename(url)
            filepath = os.path.join(self._screenshots_path, filename)

            await page.screenshot(path=filepath, full_page=self.full_page)

            print(
                f"[Screenshot] ⚠  CAPTCHA/block detected on {url}\n"
                f"[Screenshot]    Saved → {filepath}"
            )
            return filepath

        except Exception as exc:
            print(f"[Screenshot] ✗ Failed to capture screenshot for {url}: {exc}")
            return None

    @staticmethod
    def _build_filename(url: str) -> str:
        """
        Build a safe filename from a URL + timestamp.

        Example:
            https://example.com/login?foo=bar  →  example_com_login_20260603_153012.png
        """
        parsed = urlparse(url)
        # Combine netloc + path, strip leading/trailing slashes
        raw = f"{parsed.netloc}{parsed.path}".strip("/")
        # Replace any non-alphanumeric character with underscore
        safe = re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_")[:80]
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return f"{safe}_{ts}.png"
