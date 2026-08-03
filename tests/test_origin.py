"""Tests for CF-Hero output parsing, CLI argv building, and origin helpers."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from webvac.models.origin import OriginTarget
from webvac.utils.cf_hero import (
    parse_ips_from_output,
    is_cloudflare_ip,
    build_cf_hero_cmd,
    find_cf_hero_bin,
    strip_ansi,
)
from webvac.utils.origin_probe import extract_title, titles_match


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

    def test_parse_strips_ansi(self):
        text = "\x1b[32m[+] Real IP found: 203.0.113.77\x1b[0m"
        ips = parse_ips_from_output(text)
        self.assertEqual(ips, ["203.0.113.77"])

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

    def test_build_cf_hero_cmd_uses_file_not_positional(self):
        cmd = build_cf_hero_cmd(
            bin_path="/usr/bin/cf-hero",
            domain_file="/tmp/domains.txt",
            title="Example Site",
            proxy="http://127.0.0.1:8080",
            verbose=True,
            workers=8,
            extra_args=["-shodan", "-censys"],
        )
        self.assertEqual(cmd[0], "/usr/bin/cf-hero")
        self.assertIn("-f", cmd)
        self.assertIn("/tmp/domains.txt", cmd)
        self.assertNotIn("example.com", cmd)  # must not be positional
        self.assertIn("-title", cmd)
        self.assertIn("Example Site", cmd)
        self.assertIn("-px", cmd)
        self.assertIn("-shodan", cmd)
        self.assertIn("-v", cmd)
        self.assertIn("-w", cmd)

    def test_build_cf_hero_cmd_dedupes_extra_f(self):
        cmd = build_cf_hero_cmd(
            bin_path="cf-hero",
            domain_file="/tmp/a.txt",
            extra_args=["-f", "/tmp/other.txt", "-v"],
        )
        # Only our -f should remain
        self.assertEqual(cmd.count("-f"), 1)
        self.assertIn("/tmp/a.txt", cmd)
        self.assertNotIn("/tmp/other.txt", cmd)

    def test_find_cf_hero_bin_absolute(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".exe") as tf:
            path = tf.name
        try:
            found = find_cf_hero_bin(path)
            self.assertEqual(found, os.path.abspath(path))
        finally:
            os.unlink(path)

    def test_strip_ansi(self):
        self.assertEqual(strip_ansi("\x1b[31mred\x1b[0m"), "red")

    def test_origin_to_dict_roundtrip(self):
        o = OriginTarget(
            hostname="ex.com",
            origin_ip="1.2.3.4",
            validated=True,
            source="cf-hero",
            expected_title="Ex",
        )
        o2 = OriginTarget.from_dict(o.to_dict())
        self.assertEqual(o2.origin_ip, "1.2.3.4")
        self.assertTrue(o2.validated)
        self.assertEqual(o2.source, "cf-hero")


if __name__ == "__main__":
    unittest.main()
