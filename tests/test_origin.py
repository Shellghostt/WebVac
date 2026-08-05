"""Tests for origin helpers and OriginTarget."""

from __future__ import annotations

import unittest

from webvac.models.origin import OriginTarget
from webvac.utils.origin_probe import extract_title, is_cloudflare_ip, titles_match


class OriginHelperTests(unittest.TestCase):
    def test_is_cloudflare_ip(self):
        self.assertTrue(is_cloudflare_ip("104.16.42.102"))
        self.assertTrue(is_cloudflare_ip("172.67.1.1"))
        self.assertFalse(is_cloudflare_ip("203.0.113.1"))

    def test_origin_target_resolve(self):
        o = OriginTarget(hostname="example.com", origin_ip="203.0.113.5")
        self.assertEqual(
            o.resolve_fetch_url("https://example.com/path?q=1"),
            "https://203.0.113.5/path?q=1",
        )
        self.assertEqual(o.host_resolver_rule(), "MAP example.com 203.0.113.5")
        self.assertEqual(o.host_header(), "example.com")

    def test_titles_match(self):
        self.assertTrue(titles_match("Acme Corp", "Acme Corp - Home"))
        self.assertFalse(titles_match("Foo", "Bar Baz"))

    def test_extract_title(self):
        html = "<html><head><title>Hello World</title></head></html>"
        self.assertEqual(extract_title(html), "Hello World")

    def test_origin_to_dict_roundtrip(self):
        o = OriginTarget(
            hostname="ex.com",
            origin_ip="1.2.3.4",
            validated=True,
            source="manual",
            expected_title="Ex",
        )
        o2 = OriginTarget.from_dict(o.to_dict())
        self.assertEqual(o2.origin_ip, "1.2.3.4")
        self.assertTrue(o2.validated)
        self.assertEqual(o2.source, "manual")


if __name__ == "__main__":
    unittest.main()
