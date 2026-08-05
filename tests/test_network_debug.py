"""Tests for scrape network debug summarizer / dump."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from webvac.utils.network_debug import dump_network_debug, summarize_entries


class TestNetworkDebug(unittest.TestCase):
    def test_summary_hints_auth_and_challenge(self):
        entries = [
            {
                "status": 200,
                "method": "GET",
                "resource_type": "document",
                "request_url": "https://example.com/",
            },
            {
                "status": 403,
                "method": "GET",
                "resource_type": "xhr",
                "request_url": "https://example.com/api/me",
            },
            {
                "status": 200,
                "method": "GET",
                "resource_type": "script",
                "request_url": "https://example.com/cdn-cgi/challenge-platform/h/b",
                "body_preview": "",
            },
        ]
        summary = summarize_entries(entries)
        self.assertEqual(summary["entry_count"], 3)
        self.assertIn("auth_or_forbidden", summary["root_cause_hints"])
        self.assertIn("challenge_or_captcha_traffic", summary["root_cause_hints"])
        self.assertGreaterEqual(summary["failed_count"], 1)

    def test_dump_writes_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = dump_network_debug(
                output_dir=td,
                page_url="https://www.example.com/app",
                reason="bot_detected",
                entries=[{"status": 403, "method": "GET", "resource_type": "document", "request_url": "https://www.example.com/app"}],
                doc_status=403,
            )
            self.assertIsNotNone(path)
            self.assertTrue(os.path.isfile(path))
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["reason"], "bot_detected")
            self.assertEqual(data["doc_status"], 403)
            self.assertIn("summary", data)


if __name__ == "__main__":
    unittest.main()
