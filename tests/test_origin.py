"""Tests for CF-Hero output parsing and origin helpers."""

import unittest

from models.origin import OriginTarget
from utils.cf_hero import parse_ips_from_output, is_cloudflare_ip
from utils.origin_probe import extract_title, titles_match


class OriginHelperTests(unittest.TestCase):
    def test_parse_ips_from_output(self):
        text = """
        [+] Real IP found: 203.0.113.50 for example.com
        Checking 104.16.42.102 (cloudflare)
        validated origin 198.51.100.10
        """
        ips = parse_ips_from_output(text)
        self.assertIn("203.0.113.50", ips)
        self.assertIn("198.51.100.10", ips)
        self.assertNotIn("104.16.42.102", ips)

    def test_is_cloudflare_ip(self):
        self.assertTrue(is_cloudflare_ip("104.16.42.102"))
        self.assertFalse(is_cloudflare_ip("203.0.113.1"))

    def test_origin_target_resolve(self):
        o = OriginTarget(hostname="example.com", origin_ip="203.0.113.5")
        self.assertEqual(
            o.resolve_fetch_url("https://example.com/path?q=1"),
            "https://203.0.113.5/path?q=1",
        )
        self.assertEqual(o.host_resolver_rule(), "MAP example.com 203.0.113.5")

    def test_titles_match(self):
        self.assertTrue(titles_match("Acme Corp", "Acme Corp - Home"))
        self.assertFalse(titles_match("Foo", "Bar Baz"))

    def test_extract_title(self):
        html = "<html><head><title>Hello World</title></head></html>"
        self.assertEqual(extract_title(html), "Hello World")


if __name__ == "__main__":
    unittest.main()
