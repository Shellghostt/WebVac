"""
Build legacy page dicts from collector artifacts for reports and BFS crawl.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from webvac.data.html_parser import HtmlPageParser
from webvac.utils.detection import is_bot_detected_sync
from webvac.models.artifacts import HtmlArtifact, HTTPResponseArtifact
from webvac.store.artifact_store import ArtifactStore


class PageRecordBuilder:
    """Produces scrape report page dicts from the artifact store."""

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
        """Build a page record directly from HTML (no collector pipeline)."""
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

    def from_artifacts(
        self,
        store: ArtifactStore,
        url: str,
        *,
        screenshot: Optional[str] = None,
        fallback_html: str = "",
        fallback_url: str = "",
    ) -> dict:
        html_art = self._get_html_artifact(store, url)
        http_art = self._get_http_artifact(store, url)

        if html_art and html_art.raw_html:
            server_hdr = ""
            if http_art:
                server_hdr = (
                    http_art.response_headers.get("server")
                    or http_art.response_headers.get("Server")
                    or ""
                )
            data = self._parser.build_from_html(
                html_art.raw_html,
                page_url=html_art.page_url or url,
                base_url=url,
                server_header=server_hdr,
            )
        elif fallback_html:
            data = self._parser.build_from_html(
                fallback_html,
                page_url=fallback_url or url,
                base_url=url,
                server_header="",
            )
        else:
            data = self._empty_record(url)

        if http_art and http_art.status >= 400:
            data["status"] = "failed"
            data["error"] = f"HTTP {http_art.status}"
        if screenshot:
            data["screenshot"] = screenshot
        return data

    @staticmethod
    def _get_html_artifact(store: ArtifactStore, url: str) -> Optional[HtmlArtifact]:
        for art in store.get_for_url(url).get("html", []):
            if isinstance(art, HtmlArtifact):
                return art
        return None

    @staticmethod
    def _get_http_artifact(store: ArtifactStore, url: str) -> Optional[HTTPResponseArtifact]:
        for art in store.get_for_url(url).get("http", []):
            if isinstance(art, HTTPResponseArtifact):
                return art
        return None

    @staticmethod
    def _empty_record(url: str) -> dict:
        return {
            "url": url,
            "status": "failed",
            "error": "No HTML artifact collected",
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
