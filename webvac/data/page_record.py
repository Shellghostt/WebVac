"""
Build page dicts from HTML for reports and BFS crawl.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from webvac.data.html_parser import HtmlPageParser
from webvac.utils.detection import is_bot_detected_sync


class PageRecordBuilder:
    """Produces scrape report page dicts from raw HTML."""

    def __init__(
        self,
        extract_css: Optional[list[str]] = None,
        extract_xpath: Optional[list[str]] = None,
    ) -> None:
        self._parser = HtmlPageParser(
            extract_css=extract_css, extract_xpath=extract_xpath
        )

    def from_html(
        self,
        html: str,
        *,
        page_url: str,
        base_url: str = "",
        server_header: str = "",
        screenshot: Optional[str] = None,
    ) -> dict:
        """Build a page record directly from HTML."""
        data = self._parser.build_from_html(
            html,
            page_url=page_url,
            base_url=base_url or page_url,
            server_header=server_header,
        )
        from webvac.auth.wall import is_auth_wall

        if is_auth_wall(url=page_url, title=data.get("title", ""), html=html):
            data["status"] = "auth_wall"
            data["error"] = "Login/auth wall page (not scraped as content)"
        elif is_bot_detected_sync(page_url, data.get("title", ""), html):
            data["status"] = "failed"
            data["error"] = "Bot/WAF challenge page detected"
        if screenshot:
            data["screenshot"] = screenshot
        return data

    @staticmethod
    def _empty_record(url: str) -> dict:
        return {
            "url": url,
            "status": "failed",
            "error": "No HTML collected",
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "title": "",
            "meta": {},
            "open_graph": {},
            "twitter_card": {},
            "structured_data": [],
            "headings": {},
            "paragraphs": [],
            "links": [],
            "images": [],
            "tables": [],
            "lists": [],
            "forms": [],
            "media": {"videos": [], "audios": [], "iframes": []},
            "code_blocks": [],
            "emails": [],
            "phone_numbers": [],
            "social_links": [],
            "word_count": 0,
            "default_creds": [],
            "targeted_data": {},
            "screenshot": None,
        }
