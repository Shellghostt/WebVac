"""Unit tests for CMP consent helpers."""

from __future__ import annotations

import unittest

from webvac.utils.consent import apply_known_consent_bypass


class TestConsentBypass(unittest.TestCase):
    def test_deloitte_appends_hidebanner(self):
        url, note = apply_known_consent_bypass("https://www.deloitte.com/in/en.html")
        self.assertIn("hidebanner=true", url)
        self.assertIsNotNone(note)
        self.assertIn("deloitte.com", note or "")

    def test_deloitte_idempotent(self):
        url = "https://www.deloitte.com/in/en.html?hidebanner=true"
        out, note = apply_known_consent_bypass(url)
        self.assertEqual(out, url)
        self.assertIsNone(note)

    def test_preserves_other_query(self):
        url, _ = apply_known_consent_bypass(
            "https://www.deloitte.com/x?foo=1"
        )
        self.assertIn("foo=1", url)
        self.assertIn("hidebanner=true", url)

    def test_unknown_host_unchanged(self):
        url = "https://example.com/page"
        out, note = apply_known_consent_bypass(url)
        self.assertEqual(out, url)
        self.assertIsNone(note)

    def test_subdomain_match(self):
        url, note = apply_known_consent_bypass("https://careers.deloitte.com/")
        self.assertIn("hidebanner=true", url)
        self.assertIsNotNone(note)


class TestConsentCookies(unittest.TestCase):
    def test_google_consent_cookie(self):
        from webvac.utils.consent import known_consent_cookies_for_url

        cookies = known_consent_cookies_for_url("https://www.google.com/search?q=x")
        self.assertTrue(any(c["name"] == "CONSENT" and c["value"] == "YES+" for c in cookies))
        self.assertTrue(any(c["domain"] == ".google.com" for c in cookies))

    def test_non_google_no_cookie(self):
        from webvac.utils.consent import known_consent_cookies_for_url

        self.assertEqual(known_consent_cookies_for_url("https://example.com/"), [])


class TestHoneypotLinks(unittest.TestCase):
    def test_skips_hidden_links(self):
        from webvac.data.html_parser import HtmlPageParser

        html = """
        <html><body>
          <a href="/good">Visible</a>
          <a href="/trap" style="display:none">Trap</a>
          <a href="/trap2" class="hidden">Trap2</a>
          <div style="visibility:hidden"><a href="/trap3">Trap3</a></div>
          <a href="/ok2">Also visible</a>
        </body></html>
        """
        links = HtmlPageParser._links(
            __import__("bs4").BeautifulSoup(html, "lxml"),
            "https://example.com/",
        )
        urls = {l["url"] for l in links}
        self.assertIn("https://example.com/good", urls)
        self.assertIn("https://example.com/ok2", urls)
        self.assertNotIn("https://example.com/trap", urls)
        self.assertNotIn("https://example.com/trap2", urls)
        self.assertNotIn("https://example.com/trap3", urls)
