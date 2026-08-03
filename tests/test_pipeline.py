"""Unit tests for v2.1 pipeline primitives."""

import json
import os
import tempfile
import unittest

from webvac.data.html_parser import HtmlPageParser
from webvac.data.page_record import PageRecordBuilder
from webvac.models.artifacts import HtmlArtifact, HTTPResponseArtifact
from webvac.models.scan import ScanMetadata, TargetMetadata
from webvac.store.artifact_store import ArtifactStore
from webvac.store.scan_session import ScanSession


SAMPLE_HTML = (
    "<html><head><title>Acme</title></head>"
    '<body><a href="/about">About</a><form method="post">'
    '<input name="q" type="text"></form></body></html>'
)


class HtmlParserTests(unittest.TestCase):
    def test_internal_links(self):
        rec = HtmlPageParser().build_from_html(
            SAMPLE_HTML,
            page_url="https://example.com/",
            base_url="https://example.com/",
        )
        self.assertEqual(rec["title"], "Acme")
        self.assertTrue(any(l["type"] == "internal" for l in rec["links"]))
        self.assertEqual(len(rec["forms"]), 1)


class PageRecordBuilderTests(unittest.TestCase):
    def test_from_html(self):
        html = "<html><head><title>Acme</title></head><body><p>Hi</p></body></html>"
        rec = PageRecordBuilder().from_html(html, page_url="https://example.com/")
        self.assertEqual(rec["title"], "Acme")

    def test_from_artifacts(self):
        store = ArtifactStore()
        url = "https://example.com/"
        store.put(
            url,
            "html",
            HtmlArtifact(
                page_url=url,
                raw_html=SAMPLE_HTML,
                title="Acme",
                meta={},
                comments=(),
                forms=(),
                links=(),
                script_urls=(),
                inline_scripts=(),
                open_graph={},
                twitter_card={},
                canonical_url="",
                dom_hidden_elements=(),
            ),
        )
        store.put(
            url,
            "http",
            HTTPResponseArtifact(page_url=url, status=200, response_headers={"server": "nginx"}),
        )
        rec = PageRecordBuilder().from_artifacts(store, url)
        self.assertEqual(rec["status"], "success")
        self.assertEqual(rec["title"], "Acme")


class ScanSessionTests(unittest.TestCase):
    def test_parent_chain_and_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = TargetMetadata(seed_url="https://example.com")
            scan1 = ScanMetadata(target=target, scan_id="scan-aaa")
            s1 = ScanSession(tmp, scan1)
            s1.ensure_dirs()
            s1.write_meta("example-com")

            scan2 = ScanMetadata(target=target, scan_id="scan-bbb")
            s2 = ScanSession(tmp, scan2)
            parent = s2.apply_parent_chain()
            self.assertEqual(parent, s1.session_name)
            self.assertIn("scans", s2.session_dir)
            self.assertIn(s2.session_name, s2.session_dir)

            meta_path = os.path.join(s2.layout_paths()["meta"], "meta.json")
            s2.ensure_dirs()
            s2.write_meta("example-com")
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            self.assertEqual(meta["parent_scan_id"], s1.session_name)


if __name__ == "__main__":
    unittest.main()
